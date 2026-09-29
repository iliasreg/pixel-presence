# PixelPresence

PixelPresence is a small desktop companion that shows an agent’s state: idle, thinking, working, waiting, finished, or failed.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Core dependencies](https://img.shields.io/badge/Core-stdlib%20%2B%20tkinter-2E8B57)](#install-and-run)
[![MCP transport](https://img.shields.io/badge/MCP-local%20stdio-6f42c1)](#mcp-clients)

<p align="center"><img src="assets/pixelpresence-companion.svg" alt="PixelPresence ensō wisp companion" width="720"></p>

## Install and run

Requires Python 3.10+ and `tkinter`.

```bash
git clone https://github.com/iliasreg/pixel-presence.git
cd pixel-presence
./install.sh
```

The installer can connect PixelPresence to Hermes. To start the companion yourself:

```bash
python3 companion/pixel_presence.py
```

Drag the character to move it. Use `Ctrl+Shift+Space` to hide or show it, `Ctrl+Shift+Q` to quit, or right-click for the menu.

## Report state

Any script can use the CLI:

```bash
python3 cli/pixel-presence.py state working --session build --label "npm build"
python3 cli/pixel-presence.py sessions
python3 cli/pixel-presence.py clear --session build
```

## MCP clients

The optional MCP server supports local stdio clients. Install its dependency into the Python environment that will run it:

```bash
python3 -m pip install -r requirements-mcp.txt
```

Configure your MCP client to run `python3 /absolute/path/to/pixel-presence/mcp_server.py`. For Claude Code:

```bash
claude mcp add pixelpresence -- python3 /absolute/path/to/pixel-presence/mcp_server.py
```

The server provides three tools: `set_state`, `clear_state`, and `list_sessions`. Use a stable, unique session ID for each agent run. MCP does not detect lifecycle changes; clients must call the tools when the state changes. Hermes can use the hooks installed by `install.sh`.

The server uses the same session files as the companion and CLI. Set `PIXELPRESENCE_DIR` to change their location. Set `PIXELPRESENCE_SESSION_TTL_SECONDS` to change the default 600-second expiry.

## Art

The default art is `assets/enso-wisp-strip.png`. Set `PIXELPRESENCE_ART` to use another sprite sheet.
