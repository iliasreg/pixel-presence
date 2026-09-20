# PixelPresence

A small desktop companion that gives an existing AI agent a visible presence:
an Ensō Wisp in the corner of the screen that animates according to what the
agent is doing.

Current state: the companion reacts to real Hermes Agent activity.

## States

| State | Shown when | Detail line |
|---|---|---|
| `idle` | no turn running | |
| `thinking` | a turn starts (`pre_llm_call`) | |
| `working` | a tool is running or just finished (`pre_tool_call` / `post_tool_call`) | tool name |
| `waiting` | the agent needs the user (`pre_approval_request`) | |
| `success` | the turn completed (`post_llm_call`) | |
| `error` | a tool failed (`post_tool_call` with a non-ok status) | tool name |

`success` decays to `idle` after five seconds. Every state has its own sprite
frame and its own motion.

## How the agent reaches the companion

```
Hermes lifecycle event
        |
        |  shell hook
        v
adapters/hermes/pixelpresence_state.py     # maps event -> state
        |
        |  atomic write
        v
%USERPROFILE%\.pixelpresence\state.json    # the transport
        |
        |  poll every 250 ms
        v
src-tauri/src/lib.rs -> Tauri event -> src/main.ts -> sprite frame
```

The state file is the transport, because the agent and the companion run on
opposite sides of the WSL/Windows boundary. WSL is NAT-mode here, so a Hermes
process inside WSL cannot reach a listener bound to `127.0.0.1` on Windows —
the only way to keep that loopback-only constraint would be to open a Windows
port and add a firewall rule for an address that changes on reboot. A file both
sides can read avoids all of that, has no daemon to supervise, and survives
restarts by construction.

The plan's local WebSocket transport remains the right choice for a native
Linux deployment; it slots into the single `watch_state_file` function in
`src-tauri/src/lib.rs`.

## Hermes integration

The hook is one script serving several events. Apply
`adapters/hermes/config-snippet.yaml` to `~/.hermes/config.yaml`:

```bash
cmd=/mnt/c/Users/ilias/Projects/pixel-presence/adapters/hermes/pixelpresence_state.py
for ev in pre_llm_call post_llm_call pre_tool_call post_tool_call \
          pre_approval_request on_session_end; do
  hermes config set "hooks.$ev" "[{\"command\":\"$cmd\",\"timeout\":5}]" --force
done
```

Shell hooks require first-use consent per (event, command) pair. Grant it once:

```bash
HERMES_ACCEPT_HOOKS=1 hermes chat -q "hi"
hermes hooks doctor        # every entry should read allowlisted / unchanged
```

Editing the script after approval invalidates the consent (`mtime drift`).
Re-approve with `hermes hooks revoke <command>` followed by the session above.

The hook fails open: a crash or timeout logs a warning to stderr and the agent
continues. It prints nothing to stdout, so it can never block a tool call.
Changes to `~/.hermes/config.yaml` need a new session; a running session keeps
the hooks it registered at startup.

Run the mapping self-check with:

```bash
python3 adapters/hermes/pixelpresence_state.py --selftest
```

## Development

```bash
npm install
npm run dev          # frontend only, http://localhost:1420
npm run build        # tsc + vite
```

The native window must run on Windows — a WSL build cannot create a Win32
window, so `npm run tauri dev` there produces a process and no visible window.
From the Windows checkout:

```
powershell.exe -NoProfile -Command '$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=""; $vs = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"; $project = Join-Path $env:USERPROFILE "Projects\pixel-presence"; & cmd.exe /d /s /c "`"$vs`" -arch=x64 && set PATH=%USERPROFILE%\.cargo\bin;%PATH% && cd /d `"$project`" && npm run tauri dev"'
```

`VsDevCmd.bat` provides the MSVC linker and rewrites `PATH`, dropping
`%USERPROFILE%\.cargo\bin` — it has to be re-added afterwards.

`npm run tauri dev` uses the frontend served by Vite, so a frontend change
reloads without a Rust rebuild. Window placement and the state watcher live in
Rust; changing either needs a restart.

## Verifying a state change

Write a state file by hand and watch the window:

```bash
echo '{"state":"working","label":"terminal"}' > /mnt/c/Users/ilias/.pixelpresence/state.json
```

To capture the window on Windows, take a DPI-aware screenshot — a
DPI-unaware process gets virtualized coordinates and photographs the wrong
part of the desktop:

```powershell
[Dpi]::SetProcessDpiAwarenessContext([IntPtr](-4))   # before GetWindowRect/CopyFromScreen
```

## Layout

```
adapters/hermes/          hook script + config snippet
src/main.ts               state machine, sprite frame selection, drag
src/styles.css            sprite strip mapping and per-state motion
src/assets/               enso-wisp-strip.png (6 frames, 192px, 216px pitch)
src-tauri/src/lib.rs      bottom-right placement + state file watcher
src-tauri/capabilities/   window permissions (start-dragging is not in the default set)
```

## Project direction

The implementation plan lives in Obsidian at
`/mnt/z/alternance/notes/PixelPresence/PixelPresence.md`.
