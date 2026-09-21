#!/usr/bin/env python3
"""Translate a Hermes lifecycle hook payload into a PixelPresence state event.

Hermes spawns this for each subscribed hook event and pipes the payload to
stdin. The resolved state is written atomically to this session's own file
inside the directory the companion watches, which is what lets several agents
drive one companion without overwriting each other. Exit status stays 0 so a
failure here can never block a tool call.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DIR = Path("/mnt/c/Users/ilias/.pixelpresence")

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


def state_dir() -> Path:
    override = os.environ.get("PIXELPRESENCE_DIR")
    return Path(override) if override else DEFAULT_DIR


def sessions_dir() -> Path:
    return state_dir() / "sessions"


def session_id(payload: dict) -> str:
    """A filename-safe id for the writing session.

    One file per session is the whole point: two agents running at once would
    otherwise overwrite a single shared state file and each would see the
    other's state.
    """
    raw = str(payload.get("session_id") or "unknown")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._") or "unknown"
    return safe[:96]


def trace(payload: dict, state: str, detail: str | None) -> None:
    """Append what Hermes actually delivered, for latency work.

    Enabled only when PIXELPRESENCE_LOG names a file, so the normal path stays
    a single read and a single write.
    """
    target = os.environ.get("PIXELPRESENCE_LOG")
    if not target:
        return
    try:
        entry = {
            "received_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": payload.get("hook_event_name"),
            "tool": payload.get("tool_name"),
            "state": state,
            "detail": detail,
            "session_id": payload.get("session_id"),
            "hook_timestamp": payload.get("timestamp"),
            "status": (payload.get("extra") or {}).get("status"),
        }
        with open(target, "a") as handle:
            handle.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: BLE001 - tracing must never break the hook
        pass


def build_event(payload: dict, state: str, detail: str | None) -> dict:
    return {
        "version": 1,
        "type": "agent.state",
        "agent": payload.get("agent") or "hermes",
        "state": state,
        "label": detail or None,
        "session_id": payload.get("session_id"),
        "profile": payload.get("profile"),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }


def write_file_atomically(target: Path, event: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_suffix(".tmp")
    scratch.write_text(json.dumps(event))
    os.replace(scratch, target)


def write(payload: dict) -> None:
    state, detail = resolve(payload)
    if state not in STATES:
        return

    trace(payload, state, detail)
    write_file_atomically(
        sessions_dir() / f"{session_id(payload)}.json",
        build_event(payload, state, detail),
    )


def selftest() -> None:
    tool = {"hook_event_name": "pre_tool_call", "tool_name": "terminal"}
    assert resolve(tool) == ("working", "terminal")
    assert resolve({"hook_event_name": "pre_llm_call"}) == ("thinking", None)
    assert resolve({"hook_event_name": "post_llm_call"}) == ("success", None)
    assert resolve({"hook_event_name": "pre_approval_request"}) == ("waiting", None)
    assert resolve({"hook_event_name": "on_session_end"}) == ("idle", None)
    assert resolve({"hook_event_name": "subagent_start"}) == ("working", None)
    assert resolve({"hook_event_name": "on_session_start"}) == ("idle", None)
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

    # One session, one file — and an id that cannot escape the directory.
    assert session_id({"session_id": "20260921_205319_8eee71"}) == "20260921_205319_8eee71"
    assert session_id({}) == "unknown"
    assert "/" not in session_id({"session_id": "../../etc/passwd"})

    event = build_event(
        {"session_id": "s1", "goal": "x"}, "working", "terminal"
    )
    assert event["state"] == "working" and event["version"] == 1
    assert event["type"] == "agent.state" and event["agent"] == "hermes"
    assert set(event) == {
        "version",
        "type",
        "agent",
        "state",
        "label",
        "session_id",
        "profile",
        "timestamp",
    }, event

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
