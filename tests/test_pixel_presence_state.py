import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pixelpresence_state as state


class PixelPresenceStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"PIXELPRESENCE_DIR": str(self.directory)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_set_state_writes_protocol_event(self):
        state.set_state("working", "session-1", agent="codex", label="build")
        event = json.loads((self.directory / "sessions" / "session-1.json").read_text())
        self.assertEqual(event["version"], 1)
        self.assertEqual(event["type"], "agent.state")
        self.assertEqual(event["state"], "working")
        self.assertEqual(event["agent"], "codex")
        self.assertEqual(event["label"], "build")
        self.assertTrue(event["timestamp"])

    def test_set_state_rejects_invalid_state(self):
        with self.assertRaises(ValueError):
            state.set_state("running", "session-1")

    def test_session_id_is_sanitized_and_empty_rejected(self):
        state.set_state("idle", "session / one")
        self.assertTrue((self.directory / "sessions" / "session___one.json").is_file())
        with self.assertRaises(ValueError):
            state.set_state("idle", "...!!!")

    def test_clear_state_is_idempotent(self):
        state.set_state("working", "session-1")
        state.clear_state("session-1")
        state.clear_state("session-1")
        self.assertFalse((self.directory / "sessions" / "session-1.json").exists())

    def test_list_sessions_orders_by_priority_and_selects_winner(self):
        state.set_state("working", "busy", agent="hermes")
        state.set_state("waiting", "approval", agent="codex")
        result = state.list_sessions(ttl_seconds=600)
        self.assertEqual([row["session_id"] for row in result["sessions"]], ["approval", "busy"])
        self.assertEqual(result["winner"]["session_id"], "approval")

    def test_list_sessions_reports_expired_sessions_but_excludes_them_from_winner(self):
        state.set_state("error", "stale")
        os.utime(self.directory / "sessions" / "stale.json", (1, 1))
        state.set_state("working", "live")
        result = state.list_sessions(ttl_seconds=600)
        stale = next(row for row in result["sessions"] if row["session_id"] == "stale")
        self.assertTrue(stale["stale"])
        self.assertEqual(result["winner"]["session_id"], "live")

    def test_list_sessions_uses_recency_to_break_priority_ties(self):
        state.set_state("working", "older")
        state.set_state("working", "newer")
        os.utime(self.directory / "sessions" / "older.json", (time.time() - 10, time.time() - 10))
        result = state.list_sessions(ttl_seconds=600)
        self.assertEqual(result["winner"]["session_id"], "newer")

    def test_environment_override_controls_state_directory(self):
        self.assertEqual(state.state_dir(), self.directory)


if __name__ == "__main__":
    unittest.main()
