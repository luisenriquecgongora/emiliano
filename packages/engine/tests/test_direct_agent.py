"""
Unit tests for DirectAgentLoop (emiliano/direct/agent.py).
Tests tool execution, tool call parsing, and multi-turn ReAct execution without calling real LLMs.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from emiliano.direct.agent import (
    DirectAgentLoop,
    detect_verification_command,
    parse_tool_calls,
    tool_bash,
    tool_edit_file,
    tool_grep,
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

    def test_fuzzy_edit_indentation_and_whitespace(self):
        # File has 4-space indentation and trailing space
        f = Path(self.cwd, "service.py")
        f.write_text(
            "class Service:\n"
            "    def run(self): \n"
            "        return False\n",
            encoding="utf-8",
        )

        # Model proposes edit with 2-space indentation and no trailing space
        target = "  def run(self):\n    return False"
        replacement = "  def run(self):\n    return True"

        res = tool_edit_file("service.py", target, replacement, cwd=self.cwd)
        self.assertIn("Successfully edited 'service.py'", res)
        # Should be re-indented to 4 spaces cleanly
        self.assertEqual(
            f.read_text(encoding="utf-8"),
            "class Service:\n"
            "    def run(self):\n"
            "        return True\n",
        )

    def test_fuzzy_edit_over_indented_target_keeps_nesting(self):
        # Small models often indent the whole target one level too deep; nesting must survive the re-indent
        f = Path(self.cwd, "nest.py")
        f.write_text("def f():\n    if x:\n        return 1\n", encoding="utf-8")
        target = "    def f():\n        if x:\n            return 1"
        replacement = "    def f():\n        if x:\n            return 2\n        return 0"
        self.assertIn("Successfully edited", tool_edit_file("nest.py", target, replacement, cwd=self.cwd))
        self.assertEqual(f.read_text(encoding="utf-8"), "def f():\n    if x:\n        return 2\n    return 0\n")

    def test_fuzzy_edit_new_deeper_line_uses_file_indent_unit(self):
        # Target in 2-space indentation, file in 4: a new line nested deeper than the target must use 4 too
        f = Path(self.cwd, "deep.py")
        f.write_text("class A:\n    def run(self):\n        pass\n", encoding="utf-8")
        target = "  def run(self):\n    pass"
        replacement = "  def run(self):\n    if ok:\n      go()"
        tool_edit_file("deep.py", target, replacement, cwd=self.cwd)
        self.assertEqual(f.read_text(encoding="utf-8"),
                         "class A:\n    def run(self):\n        if ok:\n            go()\n")

    def test_fuzzy_edit_tabs(self):
        f = Path(self.cwd, "tabs.py")
        f.write_text("def f():\n\treturn 1\n", encoding="utf-8")
        tool_edit_file("tabs.py", "def f():\n    return 1", "def f():\n    return 2", cwd=self.cwd)
        self.assertEqual(f.read_text(encoding="utf-8"), "def f():\n\treturn 2\n")

    def test_edit_warns_when_target_is_ambiguous(self):
        f = Path(self.cwd, "dup.py")
        f.write_text("a = 1\nb = 2\na = 1\n", encoding="utf-8")
        exact = tool_edit_file("dup.py", "a = 1", "a = 9", cwd=self.cwd)
        self.assertIn("matched 2 places", exact)
        fuzzy = tool_edit_file("dup.py", "  b = 2", "  b = 3", cwd=self.cwd)
        self.assertNotIn("Warning", fuzzy)
        self.assertEqual(f.read_text(encoding="utf-8"), "a = 9\nb = 3\na = 1\n")

    def test_grep_python_fallback_matches_ripgrep_format(self):
        Path(self.cwd, "m.py").write_text("def Alpha():\n    pass\n", encoding="utf-8")
        with patch("emiliano.direct.agent.shutil.which", return_value=None):
            out = tool_grep("def alpha", cwd=self.cwd)
        self.assertIn("m.py:1: def Alpha():", out)

    def test_grep_ripgrep_output_is_normalized(self):
        Path(self.cwd, "src").mkdir()
        fake = MagicMock(stdout="src\\m.py:3:    def Alpha():\n", returncode=0)
        with patch("emiliano.direct.agent.shutil.which", return_value="rg"), \
                patch("emiliano.direct.agent.subprocess.run", return_value=fake) as run:
            out = tool_grep("def alpha", path="src", cwd=self.cwd)
        self.assertIn("src\\m.py:3: def Alpha():", out)
        cmd = run.call_args.args[0]
        self.assertIn("-i", cmd)
        self.assertEqual(cmd[-3:], ["--", "def alpha", "src"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.cwd)

    def test_grep(self):
        Path(self.cwd, "file1.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        Path(self.cwd, "file2.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
        sub = Path(self.cwd, "sub")
        sub.mkdir()
        Path(sub, "file3.py").write_text("def alpha_prime():\n    return 3\n", encoding="utf-8")

        # 1. Matching pattern across multiple files
        out = tool_grep("def alpha", cwd=self.cwd)
        self.assertIn("file1.py:1: def alpha():", out)
        self.assertIn("file3.py:1: def alpha_prime():", out)
        self.assertNotIn("file2.py", out)

        # 2. No matches found
        no_match = tool_grep("nonexistent_pattern_12345", cwd=self.cwd)
        self.assertIn("No matches found", no_match)

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

    def test_xml_grep(self):
        text = '<call:grep pattern="def total" path="src"/>'
        calls = parse_tool_calls(text)
        self.assertEqual(calls, [{"tool": "grep", "args": {"pattern": "def total", "path": "src"}}])

    def test_json_tool_call(self):
        text = '<tool_call>{"name": "read_file", "arguments": {"path": "main.py"}}</tool_call>'
        calls = parse_tool_calls(text)
        self.assertEqual(calls, [{"tool": "read_file", "args": {"path": "main.py"}}])

    def test_json_grep_call(self):
        text = '<tool_call>{"name": "grep", "arguments": {"pattern": "total"}}</tool_call>'
        calls = parse_tool_calls(text)
        self.assertEqual(calls, [{"tool": "grep", "args": {"pattern": "total"}}])

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

    def test_detect_verification_command(self):
        # 1. Custom verify.py script
        scripts_dir = Path(self.cwd, "scripts")
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "verify.py").write_text("print('verify')", encoding="utf-8")
        cmd = detect_verification_command(self.cwd)
        self.assertIsNotNone(cmd)
        self.assertIn("scripts/verify.py", cmd)

        # 2. Package.json with test script
        (scripts_dir / "verify.py").unlink()
        Path(self.cwd, "package.json").write_text('{"scripts": {"test": "jest"}}', encoding="utf-8")
        self.assertEqual(detect_verification_command(self.cwd), "npm test")

        # 3. Cargo.toml
        Path(self.cwd, "package.json").unlink()
        Path(self.cwd, "Cargo.toml").write_text('[package]\nname = "test"', encoding="utf-8")
        self.assertEqual(detect_verification_command(self.cwd), "cargo test")

    def test_verification_gate_passes(self):
        # Create a repo with a passing check
        check_script = Path(self.cwd, "scripts")
        check_script.mkdir(parents=True, exist_ok=True)
        (check_script / "verify.py").write_text("import sys; sys.exit(0)", encoding="utf-8")

        calc = Path(self.cwd, "calc.py")
        calc.write_text("x = 1\n", encoding="utf-8")

        turns = [
            '<call:edit_file path="calc.py">\n<target>x = 1</target>\n<replacement>x = 2</replacement>\n</call:edit_file>',
            'Finished updating calc.py',
        ]

        async def fake_stream(*args, **kwargs):
            reply = turns.pop(0)
            yield reply

        client = MagicMock()
        client.stream_completion = fake_stream
        client.last_usage = {"prompt_tokens": 10, "completion_tokens": 10}

        loop = DirectAgentLoop(client=client, model_id="test", auto_verify=True)
        out = asyncio.run(loop.run(goal="Update x", workspace=self.cwd))
        self.assertIn("✅ Verification passed", out)
        self.assertEqual(calc.read_text(encoding="utf-8"), "x = 2\n")

    def test_verification_gate_triggers_self_correction(self):
        # Create a verification script that fails once then passes
        state_file = Path(self.cwd, "state.txt")
        state_file.write_text("0", encoding="utf-8")

        scripts_dir = Path(self.cwd, "scripts")
        scripts_dir.mkdir(parents=True, exist_ok=True)
        # First execution fails, second passes
        v_script = (
            "import sys\n"
            "from pathlib import Path\n"
            "p = Path('state.txt')\n"
            "count = int(p.read_text().strip())\n"
            "p.write_text(str(count + 1))\n"
            "if count == 0:\n"
            "    sys.exit(1)\n"
            "sys.exit(0)\n"
        )
        (scripts_dir / "verify.py").write_text(v_script, encoding="utf-8")

        turns = [
            # Turn 1: edits file
            '<call:write_file path="app.py">\ninitial code\n</call:write_file>',
            # Turn 2: model claims it is done (triggers verification -> fails)
            'Done with initial code',
            # Turn 3: model receives verification failure, fixes the bug
            '<call:write_file path="app.py">\nfixed code\n</call:write_file>',
            # Turn 4: model claims it is done (second verification passes)
            'Done with fix',
        ]

        async def fake_stream(*args, **kwargs):
            reply = turns.pop(0)
            yield reply

        client = MagicMock()
        client.stream_completion = fake_stream
        client.last_usage = {"prompt_tokens": 10, "completion_tokens": 10}

        loop = DirectAgentLoop(client=client, model_id="test", auto_verify=True, max_turns=6)
        out = asyncio.run(loop.run(goal="Write app.py", workspace=self.cwd))
        self.assertIn("Done with fix", out)
        self.assertEqual(Path(self.cwd, "app.py").read_text(encoding="utf-8").strip(), "fixed code")


if __name__ == "__main__":
    unittest.main()
