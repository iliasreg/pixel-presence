#!/usr/bin/env python3
"""Local stdio MCP server for PixelPresence state reporting."""

from __future__ import annotations

import os
from typing import Literal

from mcp.server.fastmcp import FastMCP

from pixelpresence_state import clear_state as clear_session
from pixelpresence_state import list_sessions as read_sessions
from pixelpresence_state import safe_session_id
from pixelpresence_state import set_state as write_state

STATES = Literal["idle", "thinking", "working", "waiting", "success", "error"]
DEFAULT_TTL = float(os.environ.get("PIXELPRESENCE_SESSION_TTL_SECONDS", "600"))

mcp = FastMCP(
    "PixelPresence",
    instructions=(
        "Report the calling agent's current lifecycle state to PixelPresence. "
        "Call set_state when the state changes; MCP does not detect lifecycle events automatically. "
        "Use one stable, unique session_id per active agent session."
    ),
)


@mcp.tool()
def set_state(
    state: STATES,
    session_id: str,
    agent: str = "mcp",
    label: str | None = None,
) -> dict:
    """Set this agent session's state. Use a stable unique session_id."""
    session = safe_session_id(session_id)
    write_state(state, session, agent=agent, label=label)
    return {"ok": True, "session_id": session, "state": state}


@mcp.tool()
def clear_state(session_id: str) -> dict:
    """Clear this agent session's state when it ends."""
    session = safe_session_id(session_id)
    clear_session(session)
    return {"ok": True, "session_id": session, "cleared": True}


@mcp.tool()
def list_sessions() -> dict:
    """List current PixelPresence sessions and the state shown by the companion."""
    return read_sessions(DEFAULT_TTL)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
