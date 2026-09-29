# PixelPresence

A small desktop companion for AI agents: a character that shows what the agent
is doing — idle, thinking, working, waiting on you, finished, failed.

A Python script, not an application. Nothing to build, nothing installed
system-wide, no packaging or signing.

## Requirements

Python 3.10+ and `tkinter`, both from the standard library. The MCP server is
optional and needs one extra dependency; see [MCP server](#mcp-server).

```
Debian/Ubuntu   sudo apt install python3-tk
Fedora          sudo dnf install python3-tkinter
Windows         included with the python.org installer
```

## Install

```bash
git clone https://github.com/iliasreg/pixel-presence.git
cd pixel-presence
./install.sh
```

It asks one question — whether to launch the companion with your agent — and
**yes is the default**. Yes registers the Hermes hooks, and from the next agent
session the companion starts on its own. Hooks need first-use consent:
`HERMES_ACCEPT_HOOKS=1 hermes chat -q hi`.

## Run

```bash
python3 companion/pixel_presence.py
```

No window frame — just the character, and a caption when there is something to
say. On Windows, only one companion runs per user session; later launches exit
without opening another window.

| | |
|---|---|
| `Ctrl+Shift+Space` | show or hide |
| `Ctrl+Shift+Q` | quit |
| right-click | menu (hide, quit) |

Drag it by the character or caption; the position is saved to
`~/.pixelpresence/window.json` and restored next time.

## States

| State | Shown when | Caption |
|---|---|---|
| `idle` | no turn running | — |
| `thinking` | a turn starts | — |
| `working` | a tool or subagent runs | `using <tool>` |
| `waiting` | the agent needs you | `waiting for you` |
| `success` | the turn completed | `finished` |
| `error` | a tool failed | `<tool> failed` |

`success` settles to `idle` after five seconds; `waiting` clears when you answer
the approval.

## The protocol

One JSON file per session in `~/.pixelpresence/sessions/`, so agents never
overwrite each other and none is needed on the same machine as the companion:

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

`version` and `state` are validated; anything else is ignored. A session silent
for `600` seconds is ignored too. The most urgent live session wins, recency
breaking a tie:

```
waiting > error > working > success > thinking > idle
```

Any script or agent can drive it the same way:

```bash
python3 cli/pixel-presence.py state working --label "npm build"
python3 cli/pixel-presence.py clear --session deploy
python3 cli/pixel-presence.py sessions
```

## MCP server

The optional local stdio server lets MCP clients report and inspect session state.
It does not detect harness lifecycle events; configure the harness to call
`set_state` when its state changes and `clear_state` when its session ends.

Install the optional dependency into the Python environment that will run the
server:

```bash
python3 -m pip install -r requirements-mcp.txt
```

Configure an MCP client to launch `python3 /absolute/path/to/pixel-presence/mcp_server.py`.
The repository path must be absolute because the client may choose another
working directory. The server exposes three tools:

- `set_state(state, session_id, agent="mcp", label=null)` — states are `idle`,
  `thinking`, `working`, `waiting`, `success`, or `error`. Use a stable unique
  `session_id` for each active run.
- `clear_state(session_id)` — clear one session; safe to call more than once.
- `list_sessions()` — show sessions, stale status, and the live winner.

The server uses the same protocol files and `PIXELPRESENCE_DIR` override as the
CLI and companion. Set `PIXELPRESENCE_SESSION_TTL_SECONDS` to change the default
600-second session TTL.

Example configurations (replace `/absolute/path/to/pixel-presence` with the
checkout path):

Claude Code:

```bash
claude mcp add pixelpresence -- python3 /absolute/path/to/pixel-presence/mcp_server.py
```

Codex CLI (`~/.codex/config.toml`):

```toml
[mcp_servers.pixelpresence]
command = "python3"
args = ["/absolute/path/to/pixel-presence/mcp_server.py"]
```

Gemini CLI (`~/.gemini/settings.json`):

```json
{
  "mcpServers": {
    "pixelpresence": {
      "command": "python3",
      "args": ["/absolute/path/to/pixel-presence/mcp_server.py"]
    }
  }
}
```

Cursor (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "pixelpresence": {
      "command": "python3",
      "args": ["/absolute/path/to/pixel-presence/mcp_server.py"]
    }
  }
}
```

These clients document local stdio MCP support. This repository has protocol-level
verification, but client-specific launches have not been runtime-tested here.
Other MCP clients can connect if they support stdio and MCP tools.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PIXELPRESENCE_DIR` | `~/.pixelpresence` | sessions and window position |
| `PIXELPRESENCE_ART` | `assets/enso-wisp-strip.png` | sprite sheet |
| `PIXELPRESENCE_ART_LAYOUT` | inferred | `uei` or `wisp` |
| `PIXELPRESENCE_SESSION_TTL_SECONDS` | `600` | how long a silent session stays live |

## Art

`assets/enso-wisp-strip.png` ships. A sheet with one row per state also works —
six rows of eight 192px frames, ordered `idle, thinking, working, waiting,
success, error`. Any sheet named `assets/*.local.*` is picked up automatically,
so personal art needs no configuration:

```bash
PIXELPRESENCE_ART=assets/uei-companion-atlas.local.png python3 companion/pixel_presence.py
```

## Layout

```
install.sh                   prerequisites, then the one question
companion/pixel_presence.py  window, animation, state loop
companion/launch.ps1         starts it on Windows if not already running
cli/pixel-presence.py        state / clear / sessions for any caller
pixelpresence_state.py       shared protocol operations for CLI and MCP
mcp_server.py                optional local stdio MCP server
adapters/hermes/             maps lifecycle events to states, starts the companion
tests/                       protocol and MCP tests
assets/                      the sprite sheet that ships
```

It is a script because it used to be a Tauri app shipped as an MSI, and Windows
Defender quarantined it as `Behavior:Win32/Persistence.A!ml` — an unsigned binary
registering itself to start at login. That behaviour is gone rather than hidden:
nothing is installed and nothing is registered for login.
