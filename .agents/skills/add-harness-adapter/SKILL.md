---
name: add-harness-adapter
description: Add support for a new external coding-agent CLI (a "harness") to the Emiliano engine, or change how an existing one is launched or authenticated. Use when asked to integrate a new agent CLI, fix how a harness passes prompts, or adjust harness auth detection.
---

# Add or change a harness adapter

A harness adapter teaches the engine how to find, authenticate and run one external agent CLI.
All adapters live in `packages/engine/emiliano/harnesses/base.py` and subclass `BaseHarness`.

## Touch points (change them together)

| # | File | What to add |
|---|---|---|
| 1 | `packages/engine/emiliano/harnesses/base.py` | `class <Name>Harness(BaseHarness)` |
| 2 | `packages/engine/emiliano/core/config.py` | `<name>_cmd: str = "<binary>"` in the harness config |
| 3 | `packages/engine/emiliano/core/registry.py` | instance in `get_harness_instances()` and a weight in `prio_map` |
| 4 | `packages/engine/emiliano/core/dispatcher.py` | CLI aliases in `HARNESS_ALIASES` and the "Available:" error text |
| 5 | `packages/engine/emiliano/cli.py` | display name map and every `--harness` help string / `/switch` list |
| 6 | `packages/protocol/types.ts` + `packages/protocol/models.py` | `HarnessType` value (use the `change-protocol` skill) |
| 7 | `apps/desktop/src/renderer/chats.ts` | entry in `MODES` |
| 8 | `packages/engine/tests/` | tests (see below) |

Find every list that needs the new name: `grep -rn "opencode" packages/engine/emiliano apps/desktop/src packages/protocol`.

## The adapter

```python
class ExampleHarness(BaseHarness):
    def __init__(self, command: str = "example"):
        super().__init__(name="example", command=command, display_name="Example")

    def check_authentication(self) -> Tuple[bool, str]:
        # Env var first, then the CLI's own credentials file. Check for a real token,
        # never just that a config folder exists (that only means "launched once").
        ...

    def build_task_command(self, prompt: str) -> List[str]:
        exe = self.resolve_executable() or self.command
        return [exe, "run", prompt]

    def build_invocation(self, prompt: str) -> HarnessInvocation:
        # Preferred: keep the prompt off the command line.
        exe = self.resolve_executable() or self.command
        return HarnessInvocation(args=[exe, "run", "-"], stdin_text=prompt)
```

## Rules

- **Prompt never on argv** when the CLI can avoid it: use `stdin_text` (Claude Code, Codex) or a temp file listed in `temp_files` (OpenCode). npm CLIs are `.cmd` shims on Windows, where `CMD_METACHARS` in the prompt would be interpreted by cmd.exe; `run_task` refuses those for argv prompts.
- **Auth checks read only what they need** (`_read_json` for credential files) and never log or return secret values, only a status sentence.
- **Non-interactive mode only**: the engine streams output; the CLI must not wait for keyboard input.
- Override `get_version_command()` only if `--version` does not work (OpenCode uses `-v`).

## Tests to add

In `packages/engine/tests/test_capabilities_and_routing.py`, mirror the existing ones:
- prompt sent via stdin/temp file, not argv (`TestHarnessPromptSafety`);
- auth detected from env and from the credentials file, and "not authenticated" for an empty folder;
- `HARNESS_ALIASES` resolves the new names.

## Done when

`python scripts/verify.py` passes, and `python -m emiliano.cli harnesses` lists the new harness.
