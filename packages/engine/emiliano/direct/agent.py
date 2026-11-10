"""
Direct Agent Tool Loop for local and direct models.
Enables direct models (e.g. Ollama qwen2.5-coder, qwen3.5, deepseek) to inspect files,
perform surgical edits, run shell commands, and verify changes in a ReAct loop.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger("emiliano")

from .client import UnifiedLLMClient

AGENT_SYSTEM_PROMPT = """You are an expert autonomous coding agent working in a local software repository.
Your goal is to inspect the codebase, locate issues, make surgical code modifications, and verify your changes with tests.

You have access to the following workspace tools:
- read_file(path, start_line=1, end_line=None): Read file contents with line numbers
- edit_file(path, target, replacement): Replace exact target string with replacement string in path
- write_file(path, content): Create or overwrite a file with content
- list_dir(path="."): List files in a directory
- bash(command): Execute a shell command in the current directory and get stdout/stderr/exit code

To invoke a tool, output a tool call block using one of these formats:

Format 1 (XML - Recommended):
<call:read_file path="calc.py"/>
<call:list_dir path="."/>
<call:bash command="python check.py"/>
<call:edit_file path="calc.py">
<target>
def total(n):
    return sum(range(n))
</target>
<replacement>
def total(n):
    return sum(range(1, n + 1))
</replacement>
</call:edit_file>
<call:write_file path="new_file.py">
file content here
</call:write_file>

Format 2 (JSON):
<tool_call>
{"name": "read_file", "arguments": {"path": "calc.py"}}
</tool_call>

Workflow Guidelines:
1. Always read existing files before modifying them to understand context and exact formatting.
2. When editing code, provide exact target lines including indentation.
3. Always run the check/test command (via bash) to verify your fix.
4. When finished and all checks pass, output a concise explanation of what was done without any further tool calls.
"""


def tool_read_file(path: str, start_line: int = 1, end_line: Optional[int] = None, cwd: str = ".") -> str:
    """Reads file contents with line numbers."""
    target_path = Path(cwd) / path if not Path(path).is_absolute() else Path(path)
    if not target_path.is_file():
        return f"Error: File '{path}' does not exist."
    try:
        content = target_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total = len(lines)
        if total == 0:
            return f"{path}: (empty file)"
        start = max(1, start_line)
        end = min(total, end_line) if end_line is not None else total
        result = [f"{i}: {lines[i - 1]}" for i in range(start, end + 1)]
        return f"File: {path} (lines {start}-{end} of {total})\n" + "\n".join(result)
    except Exception as e:
        return f"Error reading file '{path}': {e}"


def tool_edit_file(path: str, target: str, replacement: str, cwd: str = ".") -> str:
    """Replaces target string with replacement in path."""
    target_path = Path(cwd) / path if not Path(path).is_absolute() else Path(path)
    if not target_path.is_file():
        return f"Error: File '{path}' does not exist."
    try:
        content = target_path.read_text(encoding="utf-8", errors="replace")
        if target not in content:
            # Try normalizing line endings
            content_lf = content.replace("\r\n", "\n")
            target_lf = target.replace("\r\n", "\n")
            if target_lf in content_lf:
                new_content = content_lf.replace(target_lf, replacement.replace("\r\n", "\n"), 1)
                target_path.write_text(new_content, encoding="utf-8")
                return f"Successfully edited '{path}'."
            return f"Error: Target text not found in '{path}'. Please inspect the file with read_file first."

        count = content.count(target)
        new_content = content.replace(target, replacement, 1)
        target_path.write_text(new_content, encoding="utf-8")
        note = f" (1 of {count} matches replaced)" if count > 1 else ""
        return f"Successfully edited '{path}'{note}."
    except Exception as e:
        return f"Error editing file '{path}': {e}"


def tool_write_file(path: str, content: str, cwd: str = ".") -> str:
    """Creates or overwrites a file with content."""
    target_path = Path(cwd) / path if not Path(path).is_absolute() else Path(path)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to '{path}'."
    except Exception as e:
        return f"Error writing file '{path}': {e}"


def tool_list_dir(path: str = ".", cwd: str = ".") -> str:
    """Lists files and directories in path."""
    target_path = Path(cwd) / path if not Path(path).is_absolute() else Path(path)
    if not target_path.is_dir():
        return f"Error: Directory '{path}' does not exist."
    try:
        items = sorted(target_path.iterdir())
        if not items:
            return f"Directory '{path}' is empty."
        lines = []
        for item in items[:150]:
            marker = "/" if item.is_dir() else ""
            lines.append(f"{item.name}{marker}")
        return f"Contents of '{path}':\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing directory '{path}': {e}"


async def tool_bash(command: str, cwd: str = ".", timeout: float = 60.0) -> str:
    """Executes a shell command in cwd and returns stdout, stderr, and exit code."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return f"Command '{command}' timed out after {timeout}s."
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        parts = [f"Exit code: {proc.returncode}"]
        if out:
            parts.append(f"STDOUT:\n{out}")
        if err:
            parts.append(f"STDERR:\n{err}")
        if not out and not err:
            parts.append("(no output)")
        return "\n".join(parts)
    except Exception as e:
        return f"Error executing command '{command}': {e}"


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    """
    Parses tool calls from model output.
    Supports:
    1. <call:tool_name attr="val">body</call:tool_name> or self-closing
    2. <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    3. Direct tags <read_file path="..."/>, <bash command="..."/>
    """
    calls: List[Dict[str, Any]] = []

    # 1. JSON tool calls: <tool_call>...</tool_call>
    for match in re.finditer(r"<tool_call>\s*({.*?})\s*</tool_call>", text, re.DOTALL):
        try:
            data = json.loads(match.group(1))
            name = data.get("name")
            args = data.get("arguments") or data.get("parameters") or {}
            if name:
                calls.append({"tool": name, "args": args})
        except Exception:
            pass

    # 2. XML call format: <call:name ...> or <name ...>
    xml_pattern = re.compile(
        r"<(?:call:)?(read_file|edit_file|write_file|list_dir|bash)"
        r"([^>]*?)(?:/>|>(.*?)</(?:call:)?\1>)",
        re.DOTALL | re.IGNORECASE,
    )
    for match in xml_pattern.finditer(text):
        tool = match.group(1).lower()
        attr_str = match.group(2)
        body = match.group(3) or ""

        # Parse inline attributes like path="..." or command="..."
        args: Dict[str, Any] = {}
        for attr_match in re.finditer(r'([a-zA-Z_]+)\s*=\s*["\']([^"\']*)["\']', attr_str):
            args[attr_match.group(1)] = attr_match.group(2)

        # For edit_file, parse <target> and <replacement> in body if present
        if tool == "edit_file":
            target_match = re.search(r"<target>(.*?)</target>", body, re.DOTALL)
            repl_match = re.search(r"<replacement>(.*?)</replacement>", body, re.DOTALL)
            if target_match and repl_match:
                # Strip leading/trailing newlines introduced by tag formatting if content inside has them
                args["target"] = target_match.group(1).strip("\r\n")
                args["replacement"] = repl_match.group(1).strip("\r\n")
            elif "target" not in args and body.strip():
                # Fallback: check if body has separator
                pass
        elif tool == "write_file":
            if "content" not in args and body:
                args["content"] = body.strip("\r\n")
        elif tool == "bash":
            if "command" not in args and body.strip():
                args["command"] = body.strip()

        if tool and (args or tool == "list_dir"):
            calls.append({"tool": tool, "args": args})

    return calls


def detect_verification_command(workspace: str = ".") -> Optional[str]:
    """Auto-detects the project's test or verification command if available."""
    root = Path(workspace).resolve()
    # 1. Custom verify script in repo
    if (root / "scripts" / "verify.py").is_file():
        return f"{sys.executable} scripts/verify.py --only python"
    # 2. Python pytest / pyproject.toml
    if (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file() or (root / "setup.cfg").is_file():
        if (root / "tests").is_dir() or (root / "test").is_dir():
            return f"{sys.executable} -m pytest"
    # 3. Node/JS package.json
    pkg_json = root / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            if "test" in scripts:
                return "npm test"
        except Exception:
            pass
    # 4. Rust Cargo.toml
    if (root / "Cargo.toml").is_file():
        return "cargo test"
    # 5. Go go.mod
    if (root / "go.mod").is_file():
        return "go test ./..."
    return None


class DirectAgentLoop:
    """
    Autonomous ReAct execution loop for local and direct models.
    Executes multiple turns, dispatching tool calls against the current workspace.
    """

    def __init__(
        self,
        client: UnifiedLLMClient,
        model_id: str,
        max_turns: int = 10,
        timeout: float = 180.0,
        auto_verify: bool = True,
    ):
        self.client = client
        self.model_id = model_id
        self.max_turns = max_turns
        self.timeout = timeout
        self.auto_verify = auto_verify
        self.files_modified: set[str] = set()
        self.last_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    async def execute_tool(self, tool_name: str, args: Dict[str, Any], cwd: str) -> str:
        """Dispatches an individual tool call."""
        if tool_name == "read_file":
            path = args.get("path") or args.get("file") or ""
            start = int(args.get("start_line", 1))
            end = int(args.get("end_line")) if args.get("end_line") is not None else None
            return tool_read_file(path, start_line=start, end_line=end, cwd=cwd)

        elif tool_name == "edit_file":
            path = args.get("path") or args.get("file") or ""
            target = args.get("target", "")
            replacement = args.get("replacement", "")
            if path:
                self.files_modified.add(path)
            return tool_edit_file(path, target=target, replacement=replacement, cwd=cwd)

        elif tool_name == "write_file":
            path = args.get("path") or args.get("file") or ""
            content = args.get("content", "")
            if path:
                self.files_modified.add(path)
            return tool_write_file(path, content=content, cwd=cwd)

        elif tool_name == "list_dir":
            path = args.get("path", ".")
            return tool_list_dir(path=path, cwd=cwd)

        elif tool_name == "bash":
            command = args.get("command") or args.get("cmd") or ""
            return await tool_bash(command, cwd=cwd)

        else:
            return f"Error: Unknown tool '{tool_name}'."

    async def run(
        self,
        goal: str,
        workspace: str = ".",
        messages: Optional[List[Dict[str, str]]] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        on_reasoning: Optional[Callable[[str], None]] = None,
        reasoning: Optional[bool] = None,
    ) -> str:
        """
        Runs the agent loop up to max_turns.
        Returns the final combined output text.
        """
        history: List[Dict[str, str]] = []
        history.append({"role": "system", "content": AGENT_SYSTEM_PROMPT})
        if messages:
            # Include prior conversation history excluding existing system prompt
            for m in messages:
                if m.get("role") != "system":
                    history.append(dict(m))
        else:
            history.append({"role": "user", "content": goal})

        full_output_parts: List[str] = []
        verification_attempted = False

        for turn in range(self.max_turns):
            logger.info(f"[DirectAgent] Turn {turn + 1}/{self.max_turns} on {self.model_id}")
            turn_chunks: List[str] = []

            async for chunk in self.client.stream_completion(
                messages=history,
                model_name=self.model_id,
                timeout=self.timeout,
                on_reasoning=on_reasoning,
                think=reasoning,
            ):
                turn_chunks.append(chunk)
                if on_chunk:
                    on_chunk(chunk)

            turn_text = "".join(turn_chunks)
            full_output_parts.append(turn_text)

            # Accumulate token usage
            if self.client.last_usage:
                self.last_usage["prompt_tokens"] += self.client.last_usage.get("prompt_tokens", 0)
                self.last_usage["completion_tokens"] += self.client.last_usage.get("completion_tokens", 0)

            # Parse tool calls from the model output
            tool_calls = parse_tool_calls(turn_text)
            if not tool_calls:
                # Automated verification gate: run checks before concluding
                if self.auto_verify and self.files_modified and not verification_attempted:
                    verification_attempted = True
                    v_cmd = detect_verification_command(workspace)
                    if v_cmd:
                        logger.info(f"[DirectAgent] Running auto-verification gate: {v_cmd}")
                        if on_chunk:
                            on_chunk(f"\n🔍 [Running verification: {v_cmd}]\n")
                        v_out = await tool_bash(v_cmd, cwd=workspace)
                        if "Exit code: 0" in v_out:
                            logger.info(f"[DirectAgent] Auto-verification passed: {v_cmd}")
                            if on_chunk:
                                on_chunk(f"\n✅ [Auto-verification passed: {v_cmd}]\n")
                            full_output_parts.append(f"\n\n✅ Verification passed: `{v_cmd}`")
                            break
                        else:
                            logger.warning(f"[DirectAgent] Auto-verification failed: {v_cmd}; prompting self-correction")
                            if on_chunk:
                                on_chunk(f"\n❌ [Auto-verification failed: {v_cmd}; entering self-correction]\n")
                            correction_prompt = (
                                f"<verification_failure command=\"{v_cmd}\">\n{v_out}\n</verification_failure>\n\n"
                                f"The verification check failed. Please inspect the errors above, fix the issues "
                                f"in the code you modified using edit_file or write_file, and verify your changes."
                            )
                            history.append({"role": "assistant", "content": turn_text})
                            history.append({"role": "user", "content": correction_prompt})
                            continue

                # No tool calls made; model has finished
                logger.info(f"[DirectAgent] Agent finished with no tool calls on turn {turn + 1}")
                break

            # Add assistant message to history
            history.append({"role": "assistant", "content": turn_text})

            # Execute tool calls
            tool_responses: List[str] = []
            for call in tool_calls:
                tool_name = call["tool"]
                args = call["args"]
                logger.info(f"[DirectAgent] Executing tool: {tool_name}({args})")
                if on_chunk:
                    on_chunk(f"\n[Executing: {tool_name} {args.get('path') or args.get('command') or ''}]\n")

                result = await self.execute_tool(tool_name, args, cwd=workspace)
                tool_responses.append(f"<tool_response name=\"{tool_name}\">\n{result}\n</tool_response>")

            tool_feedback = "\n\n".join(tool_responses)
            if on_chunk:
                on_chunk(f"\n{tool_feedback}\n")

            history.append({"role": "user", "content": tool_feedback})

        return "\n".join(full_output_parts)
