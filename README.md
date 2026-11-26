# 📋 ClipDrop

Share your clipboard (text + files) between your Mac and phone over Wi-Fi. One Python file, no dependencies.

## Run (on the Mac)

```bash
python3 clipdrop.py
```

A page opens on the Mac with a QR code. Scan it with your phone (same Wi-Fi), then "Add to Home Screen".

- **Mac → phone:** copy anything on the Mac; it appears on the phone — tap **Copy**.
- **Phone → Mac:** paste on the phone, tap **Send** — it's in the Mac clipboard, just ⌘V.
- **Files:** 📎 on the phone or drag-and-drop on the Mac. Phone uploads land in `~/Downloads/ClipDrop`.
- Access is protected by a private token in the QR link.

Allow incoming connections when macOS asks.

## Options

| Flag | Effect |
|---|---|
| `--port 8765` | Port to listen on |
| `--no-watch` | Don't auto-share the Mac clipboard (only what you send) |
| `--no-browser` | Don't open the QR page on start |
| `--new-token` | Generate a new link (old phone links stop working) |
