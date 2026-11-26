# 📋 ClipDrop

Share your clipboard (text + files) between your Mac and iPhone/Android over Wi-Fi. One Python file, no dependencies.

## 1. Run it (on the Mac)

```bash
python3 clipdrop.py --install   # starts now + automatically at every login
```

(Or `python3 clipdrop.py` to run it just in this Terminal window.)

Allow incoming connections when macOS asks. A page opens at `http://localhost:8765` with a QR code and your **Shortcut URL**.

## 2. iPhone: copy on one, paste on the other (Back Tap)

iOS doesn't let any app touch the clipboard in the background, so a tap on the back of the phone is the trigger.

**Shortcut A: "Mac → iPhone"** (Shortcuts app → **+**)
1. Add **Get Contents of URL** → paste your Shortcut URL.
2. Add **Copy to Clipboard**.

**Shortcut B: "iPhone → Mac"**
1. Add **Get Clipboard**.
2. Add **Get Contents of URL** → paste your Shortcut URL → tap ▸ → Method **POST**, Request Body **File** → pick **Clipboard**.

**Assign them:** Settings → Accessibility → Touch → **Back Tap**
- **Double Tap** → Mac → iPhone
- **Triple Tap** → iPhone → Mac

Then: **⌘C on the Mac → double-tap the phone → paste.** **Copy on the phone → triple-tap → ⌘V on the Mac.**
On the first run, allow Shortcuts to access the local network and to connect to your Mac ("Always Allow").

*Optional, fully automatic pull:* Shortcuts → Automation → **App** → pick WhatsApp, Notes, etc. → *Is Opened* → **Run Immediately** → run "Mac → iPhone". The Mac clipboard is then already on the phone whenever you open those apps.

> Tip: first check Apple's own **Universal Clipboard**: same Apple ID, Wi-Fi + Bluetooth on, **Handoff** on (Mac: System Settings → General → AirDrop & Handoff; iPhone: Settings → General → AirPlay & Handoff). When it works, it's fully automatic.

## 3. The web page (any phone)

Scan the QR code, then Share → **Add to Home Screen**.
- Mac copies show up live; tap **Copy**.
- Paste into the box and it's sent to the Mac clipboard automatically.
- Files: 📎 on the phone or drag-and-drop on the Mac. Phone uploads land in `~/Downloads/ClipDrop`.

## API

| Method | Path | |
|---|---|---|
| `GET` | `/api/clip?t=TOKEN` | Mac clipboard as plain text |
| `POST` | `/api/clip?t=TOKEN` | Raw text (or JSON `{"text": ...}`) → Mac clipboard |

## Options

| Flag | Effect |
|---|---|
| `--install` / `--uninstall` | Start at login (LaunchAgent) / remove it |
| `--port 8765` | Port to listen on |
| `--no-watch` | Don't auto-share the Mac clipboard on the web page |
| `--no-browser` | Don't open the QR page on start |
| `--new-token` | New secret link (old QR and shortcuts stop working) |

Access is protected by the secret token in the link. Logs (when installed): `~/Library/Logs/clipdrop.log`.
