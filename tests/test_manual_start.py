import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hermes_pixelpresence_hook", ROOT / "adapters/hermes/pixelpresence_state.py"
)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class ManualStartTests(unittest.TestCase):
    def test_session_start_writes_state_without_spawning(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PIXELPRESENCE_DIR": directory}):
                with patch("subprocess.Popen") as spawn, patch("subprocess.run") as run:
                    hook.write({"hook_event_name": "on_session_start", "session_id": "manual"})
                    spawn.assert_not_called()
                    run.assert_not_called()
            event = json.loads((Path(directory) / "sessions/manual.json").read_text())
            self.assertEqual(event["state"], "idle")
            self.assertEqual(event["session_id"], "manual")


@unittest.skipUnless(os.name == "posix", "installer requires a POSIX shell")
class InstallerTests(unittest.TestCase):
    def run_installer(self, answer):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            calls = directory / "calls"
            for name, body in {
                "python3": "#!/bin/sh\nexit 0\n",
                "hermes": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$INSTALLER_CALLS"\n',
            }.items():
                executable = directory / name
                executable.write_text(body)
                executable.chmod(0o755)
            env = dict(os.environ, PATH=str(directory), INSTALLER_CALLS=str(calls))
            result = subprocess.run(
                ["/bin/sh", str(ROOT / "install.sh")],
                input=answer, text=True, capture_output=True, env=env, check=True,
            )
            return result.stdout, calls.read_text() if calls.exists() else ""

    def test_empty_answer_does_not_register_hooks(self):
        output, calls = self.run_installer("\n")
        self.assertEqual(calls, "")
        self.assertIn("[y/N]", output)

    def test_eof_does_not_register_hooks(self):
        _, calls = self.run_installer("")
        self.assertEqual(calls, "")

    def test_explicit_yes_registers_state_hooks_without_promising_autostart(self):
        output, calls = self.run_installer("yes\n")
        self.assertEqual(len(calls.splitlines()), len(hook.TURN_EVENTS))
        self.assertIn("hooks.on_session_start", calls)
        self.assertNotIn("starts with every session", output)
        self.assertIn("does not start the companion", output)


if __name__ == "__main__":
    unittest.main()
