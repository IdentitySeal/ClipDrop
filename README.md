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

**Install the shortcuts (one tap each):** ClipDrop builds both shortcuts with your Mac's address already in them and signs them with macOS's `shortcuts sign` command (needs macOS 12+ and iCloud signed in on the Mac).
1. Open ClipDrop on the iPhone (scan the QR code).
2. In **⚡ iPhone shortcuts**, tap **Mac to iPhone** → *Add Shortcut*, then **iPhone to Mac** → *Add Shortcut*.
   (Or on the Mac run `python3 clipdrop.py --shortcuts` and AirDrop the two files.)
3. Settings → Accessibility → Touch → **Back Tap**: **Double Tap** = Mac to iPhone, **Triple Tap** = iPhone to Mac.

Then: **⌘C on the Mac → double-tap the phone → paste.** **Copy on the phone → triple-tap → ⌘V on the Mac.**
On the first run, allow Shortcuts to access the local network and to connect to your Mac ("Always Allow").

<details><summary>Manual setup (if signing isn't available)</summary>

Use the URL `http://<your-mac>.local:8765/api/clip?t=<token>` (printed in Terminal as *Shortcut URL*).
- **Mac to iPhone:** Get Contents of URL (that URL) → Copy to Clipboard.
- **iPhone to Mac:** Get Clipboard → Get Contents of URL (that URL, Method POST, Request Body File = Clipboard).
</details>

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
| `--shortcuts` | Build + sign the iPhone shortcuts, open the folder (for AirDrop) |
| `--port 8765` | Port to listen on |
| `--no-watch` | Don't auto-share the Mac clipboard on the web page |
| `--no-browser` | Don't open the QR page on start |
| `--new-token` | New secret link (old QR and shortcuts stop working) |

Access is protected by the secret token in the link. Logs (when installed): `~/Library/Logs/clipdrop.log`.
