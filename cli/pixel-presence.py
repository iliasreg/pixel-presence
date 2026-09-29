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
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pixelpresence_state import STATES, clear_state, list_sessions, set_state


def cmd_state(args: argparse.Namespace) -> int:
    set_state(args.state, args.session, agent=args.agent, label=args.label)
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    clear_state(args.session)
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    result = list_sessions(args.ttl)
    sessions = result["sessions"]
    if not sessions:
        print("no live sessions")
        return 0

    for session in sessions:
        if session["stale"]:
            continue
        label = f" ({session['label']})" if session["label"] else ""
        print(
            f"{session['state']:<9}{label:<24} {session['agent']:<10} "
            f"age {session['age_seconds']:5.1f}s  {session['session_id']}"
        )

    stale = sum(session["stale"] for session in sessions)
    if stale:
        print(f"{stale} session(s) older than {args.ttl:.0f}s and ignored by the companion")
    if result["winner"]:
        print(f"showing: {result['winner']['state']}")
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
