"""Shared state protocol operations for PixelPresence callers."""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

WINDOWS_USERS = Path("/mnt/c/Users")
STATES = ("idle", "thinking", "working", "waiting", "success", "error")
PRIORITY = {"waiting": 0, "error": 1, "working": 2, "success": 3, "thinking": 4, "idle": 5}


def windows_profile() -> Path | None:
    if os.environ.get("USERPROFILE"):
        return Path(os.environ["USERPROFILE"])
    if os.name == "nt" or not WINDOWS_USERS.is_dir():
        return None
    with_state = [profile for profile in sorted(WINDOWS_USERS.iterdir()) if (profile / ".pixelpresence").is_dir()]
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
    if state not in STATES:
        raise ValueError(f"unsupported state: {state}")
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


def set_state(state: str, session_id: str, agent: str = "cli", label: str | None = None) -> None:
    session = safe_session_id(session_id)
    event = build_event(state, label or None, session, agent)
    write_event(sessions_dir() / f"{session}.json", event)


def clear_state(session_id: str) -> None:
    target = sessions_dir() / f"{safe_session_id(session_id)}.json"
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def read_events() -> list[tuple[Path, dict, float]]:
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
        if not isinstance(event, dict) or event.get("version") != 1 or event.get("state") not in STATES:
            continue
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        events.append((path, event, age))
    return events


def list_sessions(ttl_seconds: float = 600) -> dict:
    rows = [
        {
            "session_id": path.stem,
            "state": event["state"],
            "label": event.get("label"),
            "agent": event.get("agent", "unknown"),
            "age_seconds": max(0.0, age),
            "stale": age > ttl_seconds,
        }
        for path, event, age in read_events()
    ]
    rows.sort(key=lambda row: (PRIORITY[row["state"]], row["age_seconds"]))
    live = [row for row in rows if not row["stale"]]
    return {"sessions": rows, "winner": live[0] if live else None}
