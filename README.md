# PixelPresence

A small desktop companion for AI agents: a character in the corner of your
screen that shows what the agent is doing. Idle, thinking, working, waiting on
you, finished, failed.

It is a Python script, not an application. There is nothing to build, nothing to
install into the system, and no signing or packaging involved. Clone it, answer
one question, run it.

## Requirements

- Python 3.8 or newer (exercised on 3.10 and 3.14)
- `tkinter` (part of the standard library, but sometimes packaged separately)

```
Debian/Ubuntu   sudo apt install python3-tk
Fedora          sudo dnf install python3-tkinter
Arch            sudo pacman -S tk
Windows         included with the python.org installer
```

Nothing else. No third-party packages, no build tools, no compiler.

## Install

```bash
git clone https://github.com/iliasreg/pixel-presence.git
cd pixel-presence
./install.sh
```

The script checks Python and `tkinter`, then asks one question: whether to
launch the companion automatically with your agent.

- **Yes** — it registers the Hermes lifecycle hooks, so the companion starts with
  a session and is showing what the agent does. Shell hooks need first-use
  consent, granted once with `HERMES_ACCEPT_HOOKS=1 hermes chat -q hi`.
- **No** — nothing else happens. Start it yourself when you want it.

## Run it

```bash
python3 companion/pixel_presence.py
```

There is no window frame: what you see is the character and, when a state has
something to say, its caption. Drag it anywhere by the character or the caption;
the position is remembered in `~/.pixelpresence/window.json` the moment you let
go, and restored next time. A remembered position that no longer lands on a
screen falls back to the bottom-right corner.

| | |
|---|---|
| `Ctrl+Shift+Space` | show or hide the companion |
| `Ctrl+Shift+Q` | quit |
| right-click | quit |

The shortcuts are system-wide, so they work whatever you are doing. They use
`RegisterHotKey`, which asks the OS for those two combinations and watches
nothing else — on other platforms the shortcuts are simply absent. Without them,
quit with `Ctrl+C` in the terminal.

## States

| State | Shown when | Caption |
|---|---|---|
| `idle` | no turn running; a session starts or ends | — |
| `thinking` | a turn starts | — |
| `working` | a tool or subagent is running | `using <tool>` |
| `waiting` | the agent needs you | `waiting for you` |
| `success` | the turn completed | `finished` |
| `error` | a tool failed | `<tool> failed` |

`idle` and `thinking` carry no caption — they are legible from the character
alone, so the companion reads as just the character most of the time. `success`
settles back to `idle` after five seconds, and `waiting` clears as soon as you
answer the approval, which is why the adapter registers
`post_approval_response` as well as `pre_approval_request`.

## The protocol

State travels as files, because an agent and the companion do not always run on
the same side of a boundary — a Hermes process inside WSL cannot reach a
listener bound to `127.0.0.1` on Windows. Files also need no daemon and survive
restarts.

One file per session, in `~/.pixelpresence/sessions/<session_id>.json`:

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

`version` and `state` are validated on read. A future protocol version, a state
outside the six, or a malformed body is ignored rather than guessed at.

A session that has not written for `PIXELPRESENCE_SESSION_TTL_SECONDS` (default
600) is ignored, so an agent that died mid-turn cannot leave the companion stuck
on `working`.

When more than one session is live the most urgent wins, and recency breaks a
tie:

```
waiting > error > working > success > thinking > idle
```

Needs beats busy: a session waiting on you is never hidden by another that is
merely running. With nothing live, the companion rests.

## Drive it from any script

`cli/pixel-presence.py` writes the same session files the Hermes hook writes, so
a build script, a test run, or another agent can move the companion without
knowing anything about Hermes. This is the way in that does not need MCP.

```bash
python3 cli/pixel-presence.py state working --label "npm build"
python3 cli/pixel-presence.py state waiting --session deploy
python3 cli/pixel-presence.py clear --session deploy
python3 cli/pixel-presence.py sessions      # what is live, and what is shown
```

Nothing is printed on success, so a caller inside a pipeline stays quiet. Errors
go to stderr with a non-zero exit — unlike the hook, which fails open because it
must never block a tool call. `--session` names the slot and defaults to `cli`.

## Hermes integration

`install.sh` wires this for you. To do it by hand, from the repository root:

```bash
cmd="$(pwd)/adapters/hermes/pixelpresence_state.py"
for ev in on_session_start pre_llm_call post_llm_call pre_tool_call \
          post_tool_call pre_approval_request post_approval_response \
          subagent_start subagent_stop on_session_end; do
  hermes config set "hooks.$ev" "[{\"command\":\"$cmd\",\"timeout\":5}]" --force
done
```

Then grant consent once and check the result:

```bash
HERMES_ACCEPT_HOOKS=1 hermes chat -q "hi"
hermes hooks doctor
```

Editing `pixelpresence_state.py` afterwards invalidates that consent (`mtime
drift`); re-approve with `hermes hooks revoke <command>` and the session above.
Config changes need a new agent session — a running one keeps the hooks it
registered at startup.

The hook fails open: a crash or timeout logs a warning and the agent continues.

## Sprite art

`assets/enso-wisp-strip.png` ships: a single six-frame strip, 192px frames on a
216px pitch, shared by every state.

A sheet with one row per state is supported too — six rows of eight 192px
frames, in the order `idle, thinking, working, waiting, success, error`. Point
the companion at it and the layout is detected from the filename:

```bash
PIXELPRESENCE_ART=assets/uei-companion-atlas.local.png python3 companion/pixel_presence.py
```

Set `PIXELPRESENCE_ART_LAYOUT=uei` or `wisp` to be explicit. Personal sheets are
git-ignored (`assets/*.local.*`) so a clone never depends on them.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PIXELPRESENCE_DIR` | `~/.pixelpresence` | where sessions and the window position live |
| `PIXELPRESENCE_ART` | `assets/enso-wisp-strip.png` | sprite sheet to draw |
| `PIXELPRESENCE_ART_LAYOUT` | inferred from the filename | `uei` or `wisp` |
| `PIXELPRESENCE_SESSION_TTL_SECONDS` | `600` | how long a silent session stays live |

## What it deliberately does not do

Earlier versions of this were a Tauri desktop application, shipped as an MSI and
an NSIS installer. Windows Defender quarantined it as
`Behavior:Win32/Persistence.A!ml` — an unsigned binary registering itself to
start at login is the textbook persistence pattern, and the detector was right
to flag it. Suppressing that with an antivirus exclusion would only fix one
machine.

So the behaviour is gone rather than hidden. Nothing is installed, nothing is
registered for login, and there is no binary to sign. In exchange, these are
gone, each because it needs either a third-party dependency or the window-hooking
APIs that made the app look like malware:

- **click-through** — the window takes clicks in its own area
- **tray icon** — no tray; use the shortcuts or right-click

The transparency is one Windows attribute (`-transparentcolor`) rather than a
layered window, and the shortcuts use `RegisterHotKey` rather than a keyboard
hook. Neither watches your input or hides the process.

## Layout

```
install.sh                 prerequisites, then the one question
companion/pixel_presence.py  the window, the sprite animation, the state loop
cli/pixel-presence.py      agent-agnostic entry point: state / clear / sessions
adapters/hermes/           hook script that maps lifecycle events to states
assets/                    the sprite sheet that ships
```

The state order above is the contract, and it appears in the companion, the CLI
and the hook. Change it in all three, or the companion and the CLI will disagree
about what is being shown.
