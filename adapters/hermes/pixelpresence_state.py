#!/usr/bin/env python3
"""Translate a Hermes lifecycle hook payload into a PixelPresence state event.

Hermes spawns this for each subscribed hook event and pipes the payload to
stdin. The resolved state is written atomically to the file the companion
watches. Exit status stays 0 so a failure here can never block a tool call.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_FILE = Path("/mnt/c/Users/ilias/.pixelpresence/state.json")

STATES = {"idle", "thinking", "working", "waiting", "success", "error"}

# `post_tool_call` reports status="ok" on success (see
# model_tools._tool_result_observer_fields); anything else it names is a failure.
SUCCESS_STATUSES = {"ok", "success", "completed"}

# Events that carry the turn's own state; the tool-name detail is added on top.
TURN_EVENTS = {
    "on_session_start": "idle",
    "pre_llm_call": "thinking",
    "pre_tool_call": "working",
    "post_tool_call": "working",
    "post_llm_call": "success",
    "on_session_end": "idle",
    "subagent_start": "working",
    "subagent_stop": "working",
    "pre_approval_request": "waiting",
    "post_approval_response": "working",
}


def resolve(payload: dict) -> tuple[str, str | None]:
    """Map a Hermes hook payload to a (state, detail) pair."""
    name = payload.get("hook_event_name") or ""
    tool = payload.get("tool_name")
    extra = payload.get("extra") or {}

    if name == "post_tool_call":
        status = extra.get("status")
        # A tool that failed mid-turn is the honest error signal; a successful
        # one means the turn is still running.
        failed = bool(status) and str(status).lower() not in SUCCESS_STATUSES
        return ("error" if failed else "working", tool)

    if name == "post_llm_call" and extra.get("interrupted"):
        return ("idle", None)

    return (TURN_EVENTS.get(name, "thinking"), tool)


def state_path() -> Path:
    override = os.environ.get("PIXELPRESENCE_STATE_FILE")
    return Path(override) if override else DEFAULT_STATE_FILE


def write(payload: dict) -> None:
    state, detail = resolve(payload)
    if state not in STATES:
        return

    event = {
        "version": 1,
        "type": "agent.state",
        "agent": "hermes",
        "state": state,
        "label": detail or None,
        "session_id": payload.get("session_id"),
        "profile": payload.get("profile"),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    target = state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_suffix(".tmp")
    scratch.write_text(json.dumps(event))
    os.replace(scratch, target)


def selftest() -> None:
    tool = {"hook_event_name": "pre_tool_call", "tool_name": "terminal"}
    assert resolve(tool) == ("working", "terminal")
    assert resolve({"hook_event_name": "pre_llm_call"}) == ("thinking", None)
    assert resolve({"hook_event_name": "post_llm_call"}) == ("success", None)
    assert resolve({"hook_event_name": "pre_approval_request"}) == ("waiting", None)
    assert resolve({"hook_event_name": "on_session_end"}) == ("idle", None)
    assert resolve({"hook_event_name": "post_tool_call", "tool_name": "patch"}) == (
        "working",
        "patch",
    )
    assert resolve(
        {
            "hook_event_name": "post_tool_call",
            "tool_name": "terminal",
            "extra": {"status": "ok"},
        }
    ) == ("working", "terminal")
    assert resolve(
        {
            "hook_event_name": "post_tool_call",
            "tool_name": "terminal",
            "extra": {"status": "error"},
        }
    ) == ("error", "terminal")
    assert resolve(
        {
            "hook_event_name": "post_tool_call",
            "tool_name": "terminal",
            "extra": {"status": "timeout"},
        }
    ) == ("error", "terminal")
    assert resolve(
        {"hook_event_name": "post_llm_call", "extra": {"interrupted": True}}
    ) == ("idle", None)
    assert resolve({"hook_event_name": "unknown_event"}) == ("thinking", None)
    print("selftest ok")


def main() -> int:
    if "--selftest" in sys.argv:
        selftest()
        return 0

    try:
        payload = json.load(sys.stdin)
        write(payload)
    except Exception as error:  # noqa: BLE001 - must never block the agent
        print(f"pixelpresence hook: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
