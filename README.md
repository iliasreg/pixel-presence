# PixelPresence

A small desktop companion for AI agents: a character that shows what the agent
is doing — idle, thinking, working, waiting on you, finished, failed.

It is a Python script, not an application. Nothing to build, nothing to install
into the system, no signing or packaging.

## Requirements

- Python 3.8+ (exercised on 3.10 and 3.14)
- `tkinter`, from the standard library

```
Debian/Ubuntu   sudo apt install python3-tk
Fedora          sudo dnf install python3-tkinter
Arch            sudo pacman -S tk
Windows         included with the python.org installer
```

## Install

```bash
git clone https://github.com/iliasreg/pixel-presence.git
cd pixel-presence
./install.sh
```

It checks Python and `tkinter`, then asks one question: whether to launch the
companion with your agent. Yes registers the Hermes hooks — they need first-use
consent, granted with `HERMES_ACCEPT_HOOKS=1 hermes chat -q hi`. No does
nothing, and you start it yourself.

## Run

```bash
python3 companion/pixel_presence.py
```

There is no window frame — just the character and, when there is something to
say, its caption.

| | |
|---|---|
| `Ctrl+Shift+Space` | show or hide |
| `Ctrl+Shift+Q` | quit |
| right-click | quit |

Drag it by the character or caption. The position is saved to
`~/.pixelpresence/window.json` when you let go, and restored next time. The
shortcuts are system-wide and use `RegisterHotKey`, which watches nothing else;
on other platforms they are simply absent. Without them, `Ctrl+C` quits.

## States

| State | Shown when | Caption |
|---|---|---|
| `idle` | no turn running; a session starts or ends | — |
| `thinking` | a turn starts | — |
| `working` | a tool or subagent is running | `using <tool>` |
| `waiting` | the agent needs you | `waiting for you` |
| `success` | the turn completed | `finished` |
| `error` | a tool failed | `<tool> failed` |

`idle` and `thinking` have no caption, so the companion usually reads as just
the character. `success` settles back to `idle` after five seconds; `waiting`
clears as soon as you answer the approval.

## The protocol

State travels as files, because an agent in WSL cannot reach a listener on
Windows. One file per session, in `~/.pixelpresence/sessions/<session_id>.json`:

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

`version` and `state` are validated; anything else is ignored rather than
guessed at. A session silent for `PIXELPRESENCE_SESSION_TTL_SECONDS` (600) is
ignored, so a dead agent cannot leave the companion stuck on `working`.

When several sessions are live the most urgent wins, and recency breaks a tie:

```
waiting > error > working > success > thinking > idle
```

## Drive it from any script

`cli/pixel-presence.py` writes the same files, for any agent or build script:

```bash
python3 cli/pixel-presence.py state working --label "npm build"
python3 cli/pixel-presence.py state waiting --session deploy
python3 cli/pixel-presence.py clear --session deploy
python3 cli/pixel-presence.py sessions
```

Silent on success; errors go to stderr with a non-zero exit. The hook instead
fails open, because it must never block a tool call.

## Hermes integration

`install.sh` wires this, using the event list in
`adapters/hermes/config-snippet.yaml`. By hand, from the repository root:

```bash
cmd="$(pwd)/adapters/hermes/pixelpresence_state.py"
hermes config set "hooks.post_tool_call" "[{\"command\":\"$cmd\",\"timeout\":5}]" --force
```

…repeated for each event in that snippet, then
`HERMES_ACCEPT_HOOKS=1 hermes chat -q "hi"` and `hermes hooks doctor`. Editing the
script afterwards invalidates that consent — re-approve with
`hermes hooks revoke <command>`. Config changes need a new agent session.

## Art

`assets/enso-wisp-strip.png` ships: six frames, 192px on a 216px pitch, shared by
every state. A sheet with one row per state is supported too — six rows of eight
192px frames, ordered `idle, thinking, working, waiting, success, error`:

```bash
PIXELPRESENCE_ART=assets/uei-companion-atlas.local.png python3 companion/pixel_presence.py
```

The layout is inferred from the filename; `PIXELPRESENCE_ART_LAYOUT=uei|wisp`
overrides it. Personal sheets are git-ignored (`assets/*.local.*`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PIXELPRESENCE_DIR` | `~/.pixelpresence` | sessions and window position |
| `PIXELPRESENCE_ART` | `assets/enso-wisp-strip.png` | sprite sheet |
| `PIXELPRESENCE_ART_LAYOUT` | inferred | `uei` or `wisp` |
| `PIXELPRESENCE_SESSION_TTL_SECONDS` | `600` | how long a silent session stays live |

## Why it is a script

It used to be a Tauri desktop app shipped as an MSI. Windows Defender
quarantined it as `Behavior:Win32/Persistence.A!ml` — an unsigned binary
registering itself to start at login is the textbook persistence pattern, and
the detector was right. An antivirus exclusion would have fixed one machine, so
the behaviour is gone rather than hidden: nothing is installed and nothing is
registered for login. Click-through and a tray icon are also absent; both need
third-party code or the window-hooking APIs that caused the problem.

## Layout

```
install.sh                   prerequisites, then the one question
companion/pixel_presence.py  window, animation, state loop
cli/pixel-presence.py        state / clear / sessions for any caller
adapters/hermes/             maps lifecycle events to states
assets/                      the sprite sheet that ships
```

The state order is the contract and appears in the companion, the CLI and the
hook. Change it in all three or they will disagree about what is shown.
