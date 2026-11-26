#!/usr/bin/env python3
"""
ClipDrop - share your clipboard (text + files) between your Mac and phone over Wi-Fi.

Run on the Mac:   python3 clipdrop.py
Then scan the QR code that opens in your Mac browser with your phone.

  - Anything you copy on the Mac appears on the phone instantly (tap "Copy").
  - Text you send from the phone lands directly in the Mac clipboard (just Cmd+V).
  - Files go both ways; files sent to the Mac are saved in ~/Downloads/ClipDrop.

Options:
  --port 8765       port to listen on
  --no-watch        don't auto-share the Mac clipboard (only share what you send manually)
  --no-browser      don't open the QR page on start
  --new-token       generate a new access link (old phone links stop working)

Pure Python standard library. macOS only (uses pbcopy/pbpaste).
"""
import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

HOME = os.path.expanduser("~")
FILES_DIR = os.path.join(HOME, "Downloads", "ClipDrop")
TOKEN_FILE = os.path.join(HOME, ".clipdrop_token")
ENV = dict(os.environ, LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
MAX_ITEMS = 60
MAX_TEXT = 2_000_000  # 2 MB of text per item is plenty

TOKEN = ""
LAN_URL = ""


# ---------------------------------------------------------------- helpers
def load_token(regenerate=False):
    if not regenerate:
        try:
            with open(TOKEN_FILE) as f:
                t = f.read().strip()
                if t:
                    return t
        except OSError:
            pass
    t = secrets.token_urlsafe(9)
    try:
        with open(TOKEN_FILE, "w") as f:
            f.write(t)
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return t


def lan_ip():
    # Preferred: ask macOS for the Wi-Fi address
    for iface in ("en0", "en1", "en2"):
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True,
                                text=True, timeout=2).stdout.strip()
            if ip:
                return ip
        except Exception:
            pass
    # Fallback: route trick (no packets are actually sent)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def mac_paste():
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, env=ENV, timeout=3).stdout
        return out.decode("utf-8", "replace")
    except Exception:
        return None


def mac_copy(text):
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=ENV, timeout=3)
        return True
    except Exception:
        return False


def safe_name(raw):
    name = os.path.basename(unquote(raw or "")).strip()
    name = re.sub(r"[^\w.\-() ]+", "_", name).strip(" .") or "file"
    base, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(FILES_DIR, candidate)):
        candidate = f"{base} ({n}){ext}"
        n += 1
    return candidate


# ---------------------------------------------------------------- state
class Store:
    def __init__(self):
        self.items = []
        self.next_id = 1
        self.cond = threading.Condition()
        self.last_clip = None  # last known Mac clipboard text (to avoid echoes)

    def add(self, kind, source, **data):
        with self.cond:
            item = dict(id=self.next_id, kind=kind, source=source, ts=time.time(), **data)
            self.next_id += 1
            self.items.append(item)
            del self.items[:-MAX_ITEMS]
            self.cond.notify_all()
            return item

    def poll(self, since, timeout=25.0):
        end = time.time() + timeout
        with self.cond:
            while True:
                latest = self.next_id - 1
                if since > latest:  # server restarted -> client must reset
                    return {"reset": True, "items": list(self.items), "latest": latest}
                new = [i for i in self.items if i["id"] > since]
                remaining = end - time.time()
                if new or remaining <= 0:
                    return {"reset": False, "items": new, "latest": latest}
                self.cond.wait(remaining)


STORE = Store()


def watch_clipboard(interval):
    first = mac_paste()
    with STORE.cond:
        STORE.last_clip = first
    if first and first.strip():
        STORE.add("text", "mac", text=first[:MAX_TEXT])
    while True:
        time.sleep(interval)
        cur = mac_paste()
        if cur is None:
            continue
        with STORE.cond:
            changed = cur != STORE.last_clip
            if changed:
                STORE.last_clip = cur
        if changed and cur.strip():
            STORE.add("text", "mac", text=cur[:MAX_TEXT])


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    server_version = "ClipDrop/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # -- auth
    def is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def authed(self):
        if self.is_local():
            return True
        q = parse_qs(urlparse(self.path).query)
        t = q.get("t", [""])[0]
        if t and secrets.compare_digest(t, TOKEN):
            return True
        c = cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return False
        return "cd" in c and secrets.compare_digest(c["cd"].value, TOKEN)

    # -- responses
    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send(code, json.dumps(obj), "application/json")

    def forbidden(self):
        self.send(403, LOCKED_HTML, "text/html; charset=utf-8")

    def read_body(self, limit):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        return self.rfile.read(n)

    # -- routes
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            return self.send(204)
        if not self.authed():
            return self.forbidden()

        if path == "/":
            html = (PAGE_HTML
                    .replace("__TOKEN__", TOKEN)
                    .replace("__LAN_URL__", LAN_URL)
                    .replace("__IS_MAC__", "true" if self.is_local() else "false"))
            return self.send(200, html, "text/html; charset=utf-8",
                             {"Set-Cookie": f"cd={TOKEN}; Path=/; Max-Age=31536000; SameSite=Lax"})

        if path == "/api/poll":
            q = parse_qs(urlparse(self.path).query)
            try:
                since = int(q.get("since", ["0"])[0])
            except ValueError:
                since = 0
            return self.send_json(STORE.poll(since))

        if path.startswith("/f/"):
            name = os.path.basename(unquote(path[3:]))
            fp = os.path.join(FILES_DIR, name)
            if not name or not os.path.isfile(fp):
                return self.send(404, "Not found")
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
            self.end_headers()
            with open(fp, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 256 * 1024)
            return

        self.send(404, "Not found")

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.authed():
            return self.forbidden()
        source = "mac" if self.is_local() else "phone"

        if path == "/api/text":
            try:
                data = json.loads(self.read_body(MAX_TEXT * 2) or b"{}")
            except Exception:
                return self.send_json({"ok": False, "error": "bad request"}, 400)
            text = str(data.get("text", ""))[:MAX_TEXT]
            if not text.strip():
                return self.send_json({"ok": False, "error": "empty"}, 400)
            with STORE.cond:
                STORE.last_clip = text  # stop the watcher re-announcing it
            copied = mac_copy(text)
            STORE.add("text", source, text=text)
            return self.send_json({"ok": True, "copied_to_mac": copied})

        if path == "/api/upload":
            os.makedirs(FILES_DIR, exist_ok=True)
            name = safe_name(self.headers.get("X-Filename", "file"))
            remaining = int(self.headers.get("Content-Length") or 0)
            fp = os.path.join(FILES_DIR, name)
            try:
                with open(fp, "wb") as f:
                    while remaining > 0:
                        chunk = self.rfile.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)
            except Exception as e:
                return self.send_json({"ok": False, "error": str(e)}, 500)
            if remaining > 0:
                try:
                    os.remove(fp)
                except OSError:
                    pass
                return self.send_json({"ok": False, "error": "upload interrupted"}, 400)
            item = STORE.add("file", source, name=name, size=os.path.getsize(fp),
                             url="/f/" + quote(name))
            if source == "phone":
                print(f"  📥 Saved from phone: {fp}")
            return self.send_json({"ok": True, "item": item})

        self.send(404, "Not found")


# ---------------------------------------------------------------- pages
LOCKED_HTML = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>ClipDrop</title><body style="font-family:-apple-system,system-ui,sans-serif;background:#0f1115;color:#e8e8e8;
display:grid;place-items:center;height:100vh;margin:0;text-align:center;padding:20px">
<div><h2>🔒 ClipDrop</h2><p>Scan the QR code shown on your Mac to connect.</p></div></body>"""

PAGE_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0f1115">
<title>ClipDrop</title>
<style>
  :root{--bg:#0f1115;--card:#181b22;--line:#262a33;--text:#e9eaee;--muted:#8b909c;--accent:#4f8cff;--ok:#2fbf71;--mac:#9b7bff;--phone:#ff9f43}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
  .wrap{max-width:720px;margin:0 auto;padding:16px}
  header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
  h1{font-size:20px;margin:0;letter-spacing:.2px}
  .dot{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)}
  .dot i{width:8px;height:8px;border-radius:50%;background:#e25555;display:inline-block}
  .dot.on i{background:var(--ok)}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}
  textarea{width:100%;min-height:90px;resize:vertical;background:#0c0e12;color:var(--text);border:1px solid var(--line);
           border-radius:10px;padding:10px;font:16px/1.4 inherit;font-family:inherit}
  .row{display:flex;gap:10px;margin-top:10px;flex-wrap:wrap}
  button,.btn{appearance:none;border:0;border-radius:10px;padding:12px 16px;font:600 15px inherit;font-family:inherit;
         background:var(--accent);color:#fff;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px}
  button.ghost,.btn.ghost{background:#252a35;color:var(--text)}
  button:active,.btn:active{transform:scale(.98)}
  .grow{flex:1}
  #qrbox{display:none;gap:16px;align-items:center}
  #qr{background:#fff;padding:10px;border-radius:10px;line-height:0}
  #qr img,#qr canvas{width:170px;height:170px}
  .url{font:13px ui-monospace,Menlo,monospace;color:var(--muted);word-break:break-all;margin-top:6px}
  .item{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:10px;animation:pop .25s ease}
  .item.latest{border-color:var(--accent)}
  @keyframes pop{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
  .meta{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-bottom:6px}
  .src.mac{color:var(--mac)} .src.phone{color:var(--phone)}
  .txt{white-space:pre-wrap;word-break:break-word;max-height:9.5em;overflow:hidden;position:relative;
       -webkit-user-select:text;user-select:text}
  .txt.open{max-height:none}
  .more{background:none;color:var(--accent);padding:4px 0;font-size:13px}
  .item .row{margin-top:8px}
  .copy{flex:1;padding:14px}
  .copy.done{background:var(--ok)}
  .file{display:flex;align-items:center;gap:10px}
  .file .n{flex:1;word-break:break-all}
  .empty{color:var(--muted);text-align:center;padding:30px 0}
  input[type=file]{display:none}
  .toast{position:fixed;left:50%;bottom:calc(20px + env(safe-area-inset-bottom));transform:translateX(-50%);background:#2b3040;
         padding:10px 16px;border-radius:10px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none}
  .toast.show{opacity:1}
  #drop{display:none;position:fixed;inset:0;background:rgba(79,140,255,.18);border:3px dashed var(--accent);
        place-items:center;font-size:22px;font-weight:600;z-index:9}
</style>
</head><body>
<div class="wrap">
  <header>
    <h1>📋 ClipDrop</h1>
    <span class="dot" id="status"><i></i><span>connecting…</span></span>
  </header>

  <div class="panel" id="qrpanel" style="display:none">
    <div id="qrbox">
      <div id="qr"></div>
      <div>
        <b>Scan with your phone</b>
        <div style="color:var(--muted);font-size:14px;margin-top:4px">Same Wi-Fi as this Mac. Then use "Add to Home Screen" so it's one tap next time.</div>
        <div class="url" id="lanurl"></div>
      </div>
    </div>
  </div>

  <div class="panel">
    <textarea id="input" placeholder="Type or paste here…"></textarea>
    <div class="row">
      <button class="grow" id="send">Send</button>
      <label class="btn ghost" for="file">📎 File</label>
      <input type="file" id="file" multiple>
    </div>
  </div>

  <div id="feed"><div class="empty" id="empty">Copy something on your Mac — it shows up here.</div></div>
</div>
<div class="toast" id="toast"></div>
<div id="drop">Drop files to share</div>

<script>
const TOKEN = "__TOKEN__", LAN_URL = "__LAN_URL__", IS_MAC = __IS_MAC__;
const $ = s => document.querySelector(s);
const feed = $("#feed"), statusEl = $("#status");
const qs = p => p + (p.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN);
let since = 0, latestEl = null;

function toast(m){const t=$("#toast");t.textContent=m;t.classList.add("show");clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove("show"),1800)}
function setStatus(on){statusEl.classList.toggle("on",on);statusEl.lastElementChild.textContent=on?"connected":"reconnecting…"}
function fmtSize(b){const u=["B","KB","MB","GB"];let i=0;while(b>=1024&&i<3){b/=1024;i++}return (i?b.toFixed(1):b)+" "+u[i]}
function fmtTime(ts){return new Date(ts*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}

// Copy that works on plain http (phones block navigator.clipboard outside https)
function copyText(text){
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(()=>true, ()=>legacyCopy(text));
  }
  return Promise.resolve(legacyCopy(text));
}
function legacyCopy(text){
  const ta=document.createElement("textarea");
  ta.value=text; ta.setAttribute("readonly","");
  Object.assign(ta.style,{position:"fixed",top:"0",left:"0",opacity:"0",fontSize:"16px"});
  document.body.appendChild(ta);
  ta.focus(); ta.select(); ta.setSelectionRange(0, text.length);
  let ok=false; try{ok=document.execCommand("copy")}catch(e){}
  ta.remove(); return ok;
}

function render(item){
  $("#empty")?.remove();
  const el=document.createElement("div"); el.className="item";
  const who = item.source==="mac" ? "💻 Mac" : "📱 Phone";
  el.innerHTML=`<div class="meta"><span class="src ${item.source}">${who}</span><span>${fmtTime(item.ts)}</span></div>`;
  if(item.kind==="text"){
    const t=document.createElement("div"); t.className="txt"; t.textContent=item.text; el.appendChild(t);
    if(item.text.split("\n").length>6 || item.text.length>400){
      const m=document.createElement("button"); m.className="more"; m.textContent="Show all";
      m.onclick=()=>{t.classList.toggle("open"); m.textContent=t.classList.contains("open")?"Show less":"Show all"};
      el.appendChild(m);
    }
    const row=document.createElement("div"); row.className="row";
    const b=document.createElement("button"); b.className="copy"; b.textContent="Copy";
    b.onclick=async()=>{const ok=await copyText(item.text);
      b.textContent=ok?"Copied ✓":"Long-press the text to copy"; b.classList.toggle("done",ok);
      setTimeout(()=>{b.textContent="Copy";b.classList.remove("done")},1600)};
    row.appendChild(b); el.appendChild(row);
  } else {
    const f=document.createElement("div"); f.className="file";
    f.innerHTML=`<span>📄</span><span class="n"></span><a class="btn ghost">Download</a>`;
    f.querySelector(".n").textContent=`${item.name} · ${fmtSize(item.size)}`;
    f.querySelector("a").href=qs(item.url);
    el.appendChild(f);
  }
  latestEl?.classList.remove("latest"); el.classList.add("latest"); latestEl=el;
  feed.prepend(el);
  while(feed.children.length>60) feed.lastElementChild.remove();
}

async function poll(){
  for(;;){
    try{
      const r=await fetch(qs("/api/poll?since="+since),{cache:"no-store"});
      if(r.status===403){document.body.innerHTML="<p style='padding:30px'>Link expired — rescan the QR code on your Mac.</p>";return}
      const d=await r.json();
      if(d.reset){feed.innerHTML="";latestEl=null}
      d.items.forEach(render);
      if(d.items.length && !IS_MAC && d.items.at(-1).source==="mac" && navigator.vibrate) navigator.vibrate(30);
      since=d.latest; setStatus(true);
    }catch(e){ setStatus(false); await new Promise(r=>setTimeout(r,2000)); }
  }
}

async function sendText(){
  const v=$("#input").value; if(!v.trim()) return;
  try{
    const r=await fetch(qs("/api/text"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:v})});
    const d=await r.json();
    if(d.ok){$("#input").value=""; toast(IS_MAC?"Shared":"On your Mac clipboard — just ⌘V")}
    else toast("Couldn't send");
  }catch(e){toast("Not connected")}
}
async function upload(files){
  for(const f of files){
    toast("Sending "+f.name+"…");
    try{
      const r=await fetch(qs("/api/upload"),{method:"POST",headers:{"X-Filename":encodeURIComponent(f.name)},body:f});
      const d=await r.json(); toast(d.ok?(IS_MAC?"Shared "+f.name:"Saved to Downloads/ClipDrop on your Mac"):"Upload failed");
    }catch(e){toast("Upload failed")}
  }
}

$("#send").onclick=sendText;
$("#input").addEventListener("keydown",e=>{if(e.key==="Enter"&&(e.metaKey||e.ctrlKey))sendText()});
$("#file").onchange=e=>{upload(e.target.files);e.target.value=""};

// Mac: drag & drop files onto the page
let dc=0; const drop=$("#drop");
addEventListener("dragenter",e=>{e.preventDefault();dc++;drop.style.display="grid"});
addEventListener("dragleave",()=>{if(--dc<=0){dc=0;drop.style.display="none"}});
addEventListener("dragover",e=>e.preventDefault());
addEventListener("drop",e=>{e.preventDefault();dc=0;drop.style.display="none";if(e.dataTransfer.files.length)upload(e.dataTransfer.files)});

// Mac view shows the QR code for the phone
if(IS_MAC){
  $("#qrpanel").style.display="block"; $("#lanurl").textContent=LAN_URL;
  const s=document.createElement("script");
  s.src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js";
  s.onload=()=>{new QRCode($("#qr"),{text:LAN_URL,width:340,height:340,correctLevel:QRCode.CorrectLevel.M});$("#qrbox").style.display="flex"};
  s.onerror=()=>{$("#qr").remove();$("#qrbox").style.display="flex"};
  document.head.appendChild(s);
}
poll();
</script>
</body></html>
"""


# ---------------------------------------------------------------- main
def main():
    global TOKEN, LAN_URL
    ap = argparse.ArgumentParser(description="Share clipboard between Mac and phone over Wi-Fi")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-watch", action="store_true", help="don't auto-share the Mac clipboard")
    ap.add_argument("--no-browser", action="store_true", help="don't open the QR page")
    ap.add_argument("--new-token", action="store_true", help="invalidate old phone links")
    ap.add_argument("--interval", type=float, default=0.6, help="clipboard check interval (s)")
    args = ap.parse_args()

    if shutil.which("pbpaste") is None:
        print("⚠️  pbpaste not found — this is meant to run on macOS.")

    TOKEN = load_token(args.new_token)
    ip = lan_ip()
    LAN_URL = f"http://{ip}:{args.port}/?t={TOKEN}"
    os.makedirs(FILES_DIR, exist_ok=True)

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    except OSError as e:
        print(f"❌ Can't start on port {args.port}: {e}\n   Is ClipDrop already running? Try --port 8766")
        sys.exit(1)
    httpd.daemon_threads = True

    if not args.no_watch:
        threading.Thread(target=watch_clipboard, args=(args.interval,), daemon=True).start()

    print("\n  📋 ClipDrop is running\n")
    print(f"  Phone link : {LAN_URL}")
    print(f"  Mac page   : http://localhost:{args.port}  (shows the QR code)")
    print(f"  Files saved: {FILES_DIR}")
    print(f"  Mac clipboard auto-share: {'OFF' if args.no_watch else 'ON'}")
    print("\n  Press Ctrl+C to stop.\n")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Bye 👋")


if __name__ == "__main__":
    main()
