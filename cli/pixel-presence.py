#!/usr/bin/env python3
"""Drive the PixelPresence companion from any script or agent.

This is the documented way in that does not require MCP: it writes the same
per-session event file the Hermes hook writes, so a build script, a test run or
another agent can move the companion without knowing anything about Hermes.

    pixel-presence.py state working --label "npm build"
    pixel-presence.py state waiting --session deploy
    pixel-presence.py clear --session deploy
    pixel-presence.py sessions

Nothing is printed on success — a caller in a pipeline should not get noise on
stdout. Errors go to stderr with a non-zero exit, unlike the Hermes hook, which
fails open because it must never block a tool call.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Where the companion keeps its state. Resolved rather than hardcoded, so the
# tool works on either side of the WSL/Windows boundary; PIXELPRESENCE_DIR
# overrides it outright.
WINDOWS_USERS = Path("/mnt/c/Users")

STATES = ("idle", "thinking", "working", "waiting", "success", "error")

# Which state wins when several sessions are live. The companion applies the
# same order, so `sessions` can explain what it is showing.
PRIORITY = {
    "waiting": 0,
    "error": 1,
    "working": 2,
    "success": 3,
    "thinking": 4,
    "idle": 5,
}


def windows_profile() -> Path | None:
    """The Windows user profile, seen from either side of the boundary.

    The companion runs on Windows, so a Linux home directory is the wrong
    place to look when this is invoked from WSL.
    """
    if os.environ.get("USERPROFILE"):
        return Path(os.environ["USERPROFILE"])
    if os.name == "nt" or not WINDOWS_USERS.is_dir():
        return None

    with_state = [
        profile
        for profile in sorted(WINDOWS_USERS.iterdir())
        if (profile / ".pixelpresence").is_dir()
    ]
    return with_state[0] if len(with_state) == 1 else None


def state_dir() -> Path:
    override = os.environ.get("PIXELPRESENCE_DIR")
    if override:
        return Path(override)
    profile = windows_profile()
    return (profile / ".pixelpresence") if profile else Path.home() / ".pixelpresence"


def sessions_dir() -> Path:
    return state_dir() / "sessions"


def safe_session_id(raw: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._")
    if not safe:
        raise ValueError("session id has no usable characters")
    return safe[:96]


def build_event(state: str, label: str | None, session: str, agent: str) -> dict:
    return {
        "version": 1,
        "type": "agent.state",
        "agent": agent,
        "state": state,
        "label": label,
        "session_id": session,
        "profile": None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    }


def write_event(target: Path, event: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_suffix(".tmp")
    scratch.write_text(json.dumps(event))
    os.replace(scratch, target)


def read_events() -> list[tuple[Path, dict, float]]:
    """Every parseable session file, with its age in seconds."""
    directory = sessions_dir()
    if not directory.is_dir():
        return []

    now = time.time()
    events = []
    for path in sorted(directory.glob("*.json")):
        try:
            event = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if event.get("version") != 1 or event.get("state") not in STATES:
            continue
        events.append((path, event, now - path.stat().st_mtime))
    return events


def cmd_state(args: argparse.Namespace) -> int:
    session = safe_session_id(args.session)
    label = args.label or None
    write_event(
        sessions_dir() / f"{session}.json",
        build_event(args.state, label, session, args.agent),
    )
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    session = safe_session_id(args.session)
    target = sessions_dir() / f"{session}.json"
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    events = read_events()
    if not events:
        print("no live sessions")
        return 0

    live = [(p, e, age) for p, e, age in events if age <= args.ttl]
    for path, event, age in sorted(live, key=lambda row: PRIORITY[row[1]["state"]]):
        label = f" ({event['label']})" if event.get("label") else ""
        print(f"{event['state']:<9}{label:<24} {event['agent']:<10} age {age:5.1f}s  {path.stem}")

    stale = len(events) - len(live)
    if stale:
        print(f"{stale} session(s) older than {args.ttl:.0f}s and ignored by the companion")
    winner = min(live, key=lambda row: PRIORITY[row[1]["state"]]) if live else None
    if winner:
        print(f"showing: {winner[1]['state']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pixel-presence",
        description="Drive the PixelPresence companion from a script or agent.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    state = sub.add_parser("state", help="set this session's state")
    state.add_argument("state", choices=STATES)
    state.add_argument("--label", help="short detail, e.g. the tool or step name")
    state.add_argument("--session", default="cli", help="session slot (default: cli)")
    state.add_argument("--agent", default="cli", help="who is reporting")
    state.set_defaults(func=cmd_state)

    clear = sub.add_parser("clear", help="drop this session's state")
    clear.add_argument("--session", default="cli", help="session slot (default: cli)")
    clear.set_defaults(func=cmd_clear)

    sessions = sub.add_parser("sessions", help="list live sessions and what is shown")
    sessions.add_argument(
        "--ttl",
        type=float,
        default=float(os.environ.get("PIXELPRESENCE_SESSION_TTL_SECONDS", 600)),
        help="seconds after which a session is ignored (default: 600)",
    )
    sessions.set_defaults(func=cmd_sessions)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as error:
        print(f"pixel-presence: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
