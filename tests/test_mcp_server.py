import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import mcp_server
except ImportError:
    mcp_server = None


@unittest.skipIf(mcp_server is None, "install requirements-mcp.txt for MCP server tests")
class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_exposes_and_executes_three_tools(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        with tempfile.TemporaryDirectory() as directory:
            root = Path(__file__).resolve().parents[1]
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(root / "mcp_server.py")],
                env={"PIXELPRESENCE_DIR": directory},
                cwd=str(root),
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual(
                        {tool.name for tool in tools.tools},
                        {"set_state", "clear_state", "list_sessions"},
                    )
                    set_tool = next(tool for tool in tools.tools if tool.name == "set_state")
                    set_schema = set_tool.model_dump(by_alias=True)["inputSchema"]
                    self.assertEqual(
                        set_schema["properties"]["state"]["enum"],
                        ["idle", "thinking", "working", "waiting", "success", "error"],
                    )
                    await session.call_tool(
                        "set_state",
                        {"state": "working", "session_id": "protocol-smoke", "agent": "test"},
                    )
                    listed = await session.call_tool("list_sessions", {})
                    payload = json.loads(listed.content[0].text)
                    self.assertEqual(payload["winner"]["session_id"], "protocol-smoke")
                    await session.call_tool("clear_state", {"session_id": "protocol-smoke"})
            self.assertFalse((Path(directory) / "sessions" / "protocol-smoke.json").exists())


@unittest.skipIf(mcp_server is None, "install requirements-mcp.txt for MCP server tests")
class MCPToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"PIXELPRESENCE_DIR": str(self.directory)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_set_state_writes_event_and_returns_safe_confirmation(self):
        result = mcp_server.set_state("working", "codex-run-1", agent="codex", label="tests")
        event = json.loads((self.directory / "sessions" / "codex-run-1.json").read_text())
        self.assertEqual(event["state"], "working")
        self.assertEqual(event["agent"], "codex")
        self.assertEqual(result["session_id"], "codex-run-1")
        self.assertNotIn(str(self.directory), str(result))

    def test_set_state_rejects_unsupported_state(self):
        with self.assertRaises(ValueError):
            mcp_server.set_state("running", "codex-run-1")

    def test_clear_state_is_idempotent(self):
        mcp_server.set_state("working", "codex-run-1")
        self.assertTrue(mcp_server.clear_state("codex-run-1")["cleared"])
        self.assertTrue(mcp_server.clear_state("codex-run-1")["cleared"])
        self.assertFalse((self.directory / "sessions" / "codex-run-1.json").exists())

    def test_list_sessions_returns_live_winner_and_stale_entries(self):
        mcp_server.set_state("error", "old-session")
        os.utime(self.directory / "sessions" / "old-session.json", (1, 1))
        mcp_server.set_state("waiting", "approval-session")
        result = mcp_server.list_sessions()
        self.assertEqual(result["winner"]["session_id"], "approval-session")
        old = next(row for row in result["sessions"] if row["session_id"] == "old-session")
        self.assertTrue(old["stale"])
