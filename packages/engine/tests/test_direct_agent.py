"""
Unit tests for DirectAgentLoop (emiliano/direct/agent.py).
Tests tool execution, tool call parsing, and multi-turn ReAct execution without calling real LLMs.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from emiliano.direct.agent import (
    DirectAgentLoop,
    parse_tool_calls,
    tool_bash,
    tool_edit_file,
    tool_list_dir,
    tool_read_file,
    tool_write_file,
)


class TestDirectAgentTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_file(self):
        Path(self.cwd, "test.txt").write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")
        out = tool_read_file("test.txt", start_line=2, end_line=3, cwd=self.cwd)
        self.assertIn("2: line 2", out)
        self.assertIn("3: line 3", out)
        self.assertNotIn("1: line 1", out)
        self.assertNotIn("4: line 4", out)

        missing = tool_read_file("nonexistent.txt", cwd=self.cwd)
        self.assertIn("Error: File 'nonexistent.txt' does not exist", missing)

    def test_edit_file(self):
        f = Path(self.cwd, "calc.py")
        f.write_text("def total(n):\n    return sum(range(n))\n", encoding="utf-8")

        res = tool_edit_file("calc.py", "sum(range(n))", "sum(range(1, n + 1))", cwd=self.cwd)
        self.assertIn("Successfully edited 'calc.py'", res)
        self.assertEqual(f.read_text(encoding="utf-8"), "def total(n):\n    return sum(range(1, n + 1))\n")

        # Target not found
        err = tool_edit_file("calc.py", "bogus_target", "new", cwd=self.cwd)
        self.assertIn("Target text not found", err)

    def test_write_file(self):
        res = tool_write_file("sub/dir/new.py", "x = 42\n", cwd=self.cwd)
        self.assertIn("Successfully wrote", res)
        f = Path(self.cwd, "sub/dir/new.py")
        self.assertTrue(f.is_file())
        self.assertEqual(f.read_text(encoding="utf-8"), "x = 42\n")

    def test_list_dir(self):
        Path(self.cwd, "a.py").write_text("", encoding="utf-8")
        Path(self.cwd, "folder").mkdir()
        out = tool_list_dir(".", cwd=self.cwd)
        self.assertIn("a.py", out)
        self.assertIn("folder/", out)

    def test_bash(self):
        res = asyncio.run(tool_bash("python -c \"print('hello-from-test')\"", cwd=self.cwd))
        self.assertIn("Exit code: 0", res)
        self.assertIn("hello-from-test", res)


class TestParseToolCalls(unittest.TestCase):
    def test_xml_read_file(self):
        text = 'Let me inspect calc.py:\n<call:read_file path="calc.py"/>'
        calls = parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], {"tool": "read_file", "args": {"path": "calc.py"}})

    def test_xml_edit_file(self):
        text = (
            'I will fix the bug:\n'
            '<call:edit_file path="calc.py">\n'
            '<target>\n'
            'def total(n):\n'
            '    return sum(range(n))\n'
            '</target>\n'
            '<replacement>\n'
            'def total(n):\n'
            '    return sum(range(1, n + 1))\n'
            '</replacement>\n'
            '</call:edit_file>'
        )
        calls = parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool"], "edit_file")
        self.assertEqual(calls[0]["args"]["path"], "calc.py")
        self.assertEqual(calls[0]["args"]["target"], "def total(n):\n    return sum(range(n))")
        self.assertEqual(calls[0]["args"]["replacement"], "def total(n):\n    return sum(range(1, n + 1))")

    def test_xml_bash(self):
        text = '<call:bash command="python check.py"/>'
        calls = parse_tool_calls(text)
        self.assertEqual(calls, [{"tool": "bash", "args": {"command": "python check.py"}}])

    def test_json_tool_call(self):
        text = '<tool_call>{"name": "read_file", "arguments": {"path": "main.py"}}</tool_call>'
        calls = parse_tool_calls(text)
        self.assertEqual(calls, [{"tool": "read_file", "args": {"path": "main.py"}}])

    def test_no_tool_calls(self):
        text = "I have reviewed the code and everything looks correct."
        calls = parse_tool_calls(text)
        self.assertEqual(calls, [])


class TestDirectAgentLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_loop_executes_tools_and_finishes(self):
        calc = Path(self.cwd, "calc.py")
        calc.write_text("def total(n):\n    return sum(range(n))\n", encoding="utf-8")

        turns = [
            '<call:read_file path="calc.py"/>',
            '<call:edit_file path="calc.py">\n<target>sum(range(n))</target>\n<replacement>sum(range(1, n + 1))</replacement>\n</call:edit_file>',
            'The off-by-one bug in calc.py has been fixed.',
        ]

        async def fake_stream(*args, **kwargs):
            reply = turns.pop(0)
            yield reply

        client = MagicMock()
        client.stream_completion = fake_stream
        client.last_usage = {"prompt_tokens": 50, "completion_tokens": 20}

        chunks = []
        loop = DirectAgentLoop(client=client, model_id="ollama/qwen3.5:2b", max_turns=5)
        out = asyncio.run(loop.run(
            goal="Fix calc.py",
            workspace=self.cwd,
            on_chunk=chunks.append,
        ))

        self.assertIn("The off-by-one bug in calc.py has been fixed.", out)
        self.assertEqual(calc.read_text(encoding="utf-8"), "def total(n):\n    return sum(range(1, n + 1))\n")
        self.assertGreater(loop.last_usage["completion_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
