# PixelPresence

A small desktop companion that gives an existing AI agent a visible presence:
an Ensō Wisp in the corner of the screen that animates according to what the
agent is doing.

Current state: the companion reacts to real Hermes Agent activity.

## States

| State | Shown when | Detail line |
|---|---|---|
| `idle` | no turn running; a session starts or ends (`on_session_start` / `on_session_end`) | |
| `thinking` | a turn starts (`pre_llm_call`) | |
| `working` | a tool is running or just finished (`pre_tool_call` / `post_tool_call`), or a subagent is running (`subagent_start` / `subagent_stop`) | tool name |
| `waiting` | the agent needs the user (`pre_approval_request`) | |
| `success` | the turn completed (`post_llm_call`) | |
| `error` | a tool failed (`post_tool_call` with a non-ok status) | tool name |

`success` decays to `idle` after five seconds. Every state has its own sprite
frame and its own motion.

The caption only appears for `working`, `waiting`, `success` and `error` —
`idle` and `thinking` are legible from the character alone, so the companion
reads as just the character the rest of the time.

## Window behaviour

- **Tray icon** with `Show / Hide` and `Quit PixelPresence`. Left-click the icon
  to toggle the companion; right-click for the menu. `Ctrl+Shift+Space` toggles
  and `Ctrl+Shift+Q` quits from anywhere.
- **Position is remembered** in `%USERPROFILE%\.pixelpresence\window.json` and
  restored on the next start; a position that no longer lands on a monitor
  falls back to the bottom-right corner.
- **Click-through.** Only the character is interactive. Everywhere else the
  window is transparent and lets clicks fall through to whatever is behind it,
  so the companion does not act as an invisible blocker. The pointer is polled
  because a window that is ignoring cursor events cannot report arrivals; the
  window is handed its input back whenever a menu is open, since a menu can
  extend past the character.
- **Start with Windows** is a tray toggle, off until you turn it on. It is only
  offered by an installed build: a debug build runs from the cargo target
  directory and needs the Vite dev server to render, so registering it to launch
  at login would put a blank window on screen at every boot. Turn it on from the
  *installed* copy — it registers the path of the binary doing the enabling, and
  a binary sitting in the cargo target directory disappears on the next
  `cargo clean`.

## How the agent reaches the companion

```
Hermes lifecycle event
        |
        |  shell hook
        v
adapters/hermes/pixelpresence_state.py        # maps event -> state
        |
        |  atomic write, one file per session
        v
%USERPROFILE%\.pixelpresence\sessions\<id>.json
        |
        |  poll every 250 ms, show the most urgent live session
        v
src-tauri/src/lib.rs -> Tauri event -> src/main.ts -> sprite frame
```

Files are the transport, because the agent and the companion run on opposite
sides of the WSL/Windows boundary. WSL is NAT-mode here, so a Hermes process
inside WSL cannot reach a listener bound to `127.0.0.1` on Windows — the only
way to keep that loopback-only constraint would be to open a Windows port and
add a firewall rule for an address that changes on reboot. Files both sides can
read avoid all of that, have no daemon to supervise, and survive restarts by
construction.

The plan's local WebSocket transport remains the right choice for a native
Linux deployment; it slots into `watch_sessions` in `src-tauri/src/lib.rs`.

## The protocol

One file per session, so several agents can drive one companion instead of
overwriting a single shared state file. A session that has not written for
`PIXELPRESENCE_SESSION_TTL_SECONDS` (default 600) is ignored, so an agent that
died mid-turn cannot leave the companion stuck on `working`.

```json
{
  "version": 1,
  "type": "agent.state",
  "agent": "hermes",
  "state": "working",
  "label": "terminal",
  "session_id": "20260921_134428_8247f9",
  "profile": null,
  "timestamp": "2026-09-21T12:14:22.467+00:00"
}
```

`version` and `state` are validated on read. Anything else — a future protocol
version, a state outside the six, a malformed body — is ignored rather than
guessed at.

When more than one session is live the most urgent wins, and recency breaks a
tie:

```
waiting > error > working > success > thinking > idle
```

Needs beats busy: a session waiting on the user is never hidden by another
session that is merely running. With nothing live, the companion rests.

## Drive it from any script

`cli/pixel-presence.py` writes the same session files the Hermes hook does, so a
build script, a test run or another agent can move the companion without knowing
anything about Hermes. This is the way in that does not require MCP.

```bash
python3 cli/pixel-presence.py state working --label "npm build"
python3 cli/pixel-presence.py state waiting --session deploy
python3 cli/pixel-presence.py clear --session deploy
python3 cli/pixel-presence.py sessions      # what is live, and what is shown
```

Nothing is printed on success, so a caller inside a pipeline stays quiet.
Errors go to stderr with a non-zero exit — unlike the hook, which fails open
because it must never block a tool call.

`--session` names the slot, defaulting to `cli`; two concurrent callers should
pass different values. The directory is overridable with `PIXELPRESENCE_DIR` so
the tool can be pointed at another machine's companion.

## Hermes integration

The hook is one script serving several events. Apply
`adapters/hermes/config-snippet.yaml` to `~/.hermes/config.yaml`:

```bash
cmd=/mnt/c/Users/ilias/Projects/pixel-presence/adapters/hermes/pixelpresence_state.py
for ev in on_session_start pre_llm_call post_llm_call pre_tool_call \
          post_tool_call pre_approval_request subagent_start subagent_stop \
          on_session_end; do
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
reloads without a Rust rebuild. Window placement, the tray and the session
watcher live in Rust; changing any of them needs a restart.

## Install on Windows

Use an installer built from a release, not `pixel-presence.exe` from a cargo
target directory. The target directory is development output and can disappear
on the next `cargo clean`.

1. Download either installer from the release bundle:

   - `PixelPresence_<version>_x64-setup.exe` — NSIS installer
   - `PixelPresence_<version>_x64_en-US.msi` — Windows Installer package

2. Open the downloaded file and complete the Windows installer. The NSIS
   installer places the app in `%LOCALAPPDATA%\PixelPresence`; the MSI uses its
   Windows-managed install location. Both add a Start Menu shortcut.
3. Launch **PixelPresence** from the Start Menu. It needs no terminal or Vite
   dev server; the frontend and shipped companion art are embedded in the app.
4. To launch it automatically after signing in, right-click its tray icon and
   select **Start with Windows**. Enable this only from the installed app, never
   from a debug or cargo-target executable.

The tray menu also provides **Show / Hide** and **Quit PixelPresence**. The
keyboard shortcuts are `Ctrl+Shift+Space` to toggle visibility and
`Ctrl+Shift+Q` to quit.

## Building an installer

```bash
npm run tauri build      # then find the bundles under the cargo target dir
```

This produces a release binary with the frontend embedded (so it runs with no
dev server) plus MSI and NSIS installers under
`$CARGO_TARGET_DIR/release/bundle/`. The first run also downloads the WiX and
NSIS toolchains, and `lto = true` in `Cargo.toml` makes a release build slow —
minutes, not seconds.

An installed build serves the shipped default art; the local art override
described below only applies to builds made from a checkout that has
`.env.local`.

## Verifying a state change

The CLI is the shortest path — it writes what the hook writes:

```bash
python3 cli/pixel-presence.py state working --label "hello"
python3 cli/pixel-presence.py sessions
python3 cli/pixel-presence.py clear
```

To capture the window on Windows, take a DPI-aware screenshot — a
DPI-unaware process gets virtualized coordinates and photographs the wrong
part of the desktop:

```powershell
[Dpi]::SetProcessDpiAwarenessContext([IntPtr](-4))   # before GetWindowRect/CopyFromScreen
```

## Local sprite art

`src/assets/enso-wisp-strip.png` is the art that ships. To try different art
without making it the default, put a 6-row x N-frame atlas at 192px per frame in
`public/` and point `.env.local` at it:

```
VITE_PIXELPRESENCE_ART=/uei-companion-atlas.local.png
```

`src/styles.css` and `src/main.ts` read that variable; with it unset the build
falls back to the shipped strip. The atlas and `.env.local` are deliberately
untracked, so a clone never depends on local art.

## Layout

```
adapters/hermes/          hook script + config snippet
cli/pixel-presence.py     agent-agnostic entry point: state / clear / sessions
src/main.ts               state machine, sprite frame selection, drag
src/styles.css            sprite strip mapping and per-state motion
src/assets/               enso-wisp-strip.png (6 frames, 192px, 216px pitch)
src-tauri/src/lib.rs      tray, remembered position, click-through hit test,
                          session aggregation, state file watcher
src-tauri/capabilities/   window permissions (start-dragging is not in the default set)
```

## Project direction

The implementation plan lives in Obsidian at
`/mnt/z/alternance/notes/PixelPresence/PixelPresence.md`.
