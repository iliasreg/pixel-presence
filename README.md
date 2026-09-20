# PixelPresence

PixelPresence is a lightweight desktop companion that gives an existing AI agent a small retro presence on the desktop.

Current work is Phase 1: the Tauri desktop shell.

## Phase 1

- Tauri 2 desktop application
- Transparent frameless window
- Always-on-top configuration
- Small pixel companion rendered with CSS
- Idle animation
- Drag-region support
- Bottom-right-friendly 300×300 window

Agent integrations and event handling are intentionally not implemented yet.

## Development

```bash
npm install
npm run dev
```

The frontend can be smoke-tested in a browser at `http://127.0.0.1:1420/`.

To run the native Tauri shell:

```bash
npm run tauri dev
```

The Linux environment needs Tauri's GTK/WebKit development prerequisites before the native command can run. The TypeScript frontend already builds successfully with:

```bash
npm run build
```

## Project direction

The implementation plan is documented in Obsidian:

`/mnt/z/alternance/notes/PixelPresence/PixelPresence.md`
