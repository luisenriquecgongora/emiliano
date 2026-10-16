"""
Command-line Interface for Emiliano.
Allows launching the daemon server or running standalone tasks directly in terminal.
Features fast startup (lazy imports), provider discovery, doctor diagnostics,
and unified routing across direct models and agent harnesses.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Optional
import click
from .core.config import load_config
from .core.single_instance import SingleInstanceGuard

try:
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style
    PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    PROMPT_TOOLKIT_AVAILABLE = False
    class Completer:
        pass
    class Completion:
        def __init__(self, text: str, start_position: int = 0, display: str = None, display_meta: str = None):
            self.text = text
            self.start_position = start_position
            self.display = display or text
            self.display_meta = display_meta


class SlashCommandCompleter(Completer):
    """Floating dropdown completer for slash commands and sub-arguments."""

    COMMANDS = {
        "/switch": "Switch active harness or provider (claude, agy, codex, ollama, auto)",
        "/policy": "Change execution routing policy (auto, local, harness, api)",
        "/model": "Override the active model name (e.g. qwen3.5:2b)",
        "/doctor": "Run diagnostic check of models, credentials, and harnesses",
        "/models": "List detected local Ollama models and remote API providers",
        "/harnesses": "List external CLI agent harnesses and auth status",
        "/clear": "Reset conversation memory context",
        "/history": "Show current conversation turn count",
        "/help": "Display command list and keyboard shortcuts",
        "/exit": "Quit the interactive session",
    }

    SWITCH_TARGETS = {
        "agy": "Antigravity CLI Agent (Gemini)",
        "claude": "Claude Code CLI Agent (Anthropic)",
        "codex": "OpenAI Codex CLI Agent",
        "opencode": "OpenCode CLI Agent",
        "ollama": "Local Ollama Runtime",
        "anthropic": "Direct Anthropic Claude API",
        "openai": "Direct OpenAI GPT API",
        "deepseek": "Direct DeepSeek API",
        "gemini": "Direct Google Gemini API",
        "auto": "Automatic Intent-Aware Routing",
    }

    POLICIES = {
        "auto": "Intent-aware automatic routing (default)",
        "local": "Local-only execution via Ollama",
        "harness": "Prioritize external agent harnesses",
        "api": "Direct remote frontier APIs",
    }

    def get_completions(self, document, complete_event=None):
        text = document.text_before_cursor
        stripped = text.lstrip()

        # 1. Primary command completion on '/'
        if stripped.startswith("/") and " " not in stripped:
            word = stripped
            for cmd, desc in self.COMMANDS.items():
                if cmd.lower().startswith(word.lower()):
                    yield Completion(
                        cmd,
                        start_position=-len(word),
                        display=cmd,
                        display_meta=desc,
                    )
            return

        # 2. Sub-argument completion for /switch <target>
        if stripped.startswith("/switch ") or stripped.startswith("switch "):
            parts = stripped.split()
            current_arg = parts[1] if len(parts) > 1 and not stripped.endswith(" ") else ""
            for target, desc in self.SWITCH_TARGETS.items():
                if target.lower().startswith(current_arg.lower()):
                    yield Completion(
                        target,
                        start_position=-len(current_arg),
                        display=target,
                        display_meta=desc,
                    )
            return

        # 3. Sub-argument completion for /policy <p>
        if stripped.startswith("/policy ") or stripped.startswith("policy "):
            parts = stripped.split()
            current_arg = parts[1] if len(parts) > 1 and not stripped.endswith(" ") else ""
            for pol, desc in self.POLICIES.items():
                if pol.lower().startswith(current_arg.lower()):
                    yield Completion(
                        pol,
                        start_position=-len(current_arg),
                        display=pol,
                        display_meta=desc,
                    )
            return


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context):
    """Emiliano: Unified Meta-Harness & Desktop Cowork Platform."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(chat)


@cli.command()
@click.option("--port", default=8765, help="WebSocket IPC server port")
@click.option("--host", default="127.0.0.1", help="Binding host")
def server(host: str, port: int):
    """Start the Emiliano Engine background daemon."""
    import uvicorn

    guard = SingleInstanceGuard()
    if not guard.acquire():
        click.echo("[Error] Another instance of Emiliano Engine daemon is already running.", err=True)
        sys.exit(1)

    click.echo(f"Starting Emiliano Engine daemon on ws://{host}:{port}/ws...")
    try:
        uvicorn.run("emiliano.server.app:app", host=host, port=port, log_level="info")
    finally:
        guard.release()


@cli.command()
def harnesses():
    """Check availability, version, and authentication of external agent harnesses."""
    from .core.registry import CapabilityRegistry
    from .core.capabilities import CapabilityStatus

    config = load_config()
    registry = CapabilityRegistry(config=config)

    click.echo(click.style("External Agent Harness Status:", bold=True))

    async def _check():
        caps = await registry.discover_all(test_harness_usability=True)
        harnesses_list = [c for c in caps.values() if c.execution_type.value == "agent_harness"]
        for h in harnesses_list:
            if h.status == CapabilityStatus.READY:
                status_str = click.style(f"Ready ({h.version or 'ok'})", fg="green")
            elif h.status == CapabilityStatus.UNAUTHENTICATED:
                status_str = click.style(f"Unauthenticated ({h.status_message})", fg="yellow")
            elif h.status == CapabilityStatus.UNAVAILABLE:
                status_str = click.style(f"Unavailable ({h.status_message})", fg="yellow")
            else:
                status_str = click.style("Not Found in PATH", fg="red")

            path_str = f" [{h.executable_path}]" if h.executable_path else ""
            click.echo(f"  • {click.style(h.display_name, bold=True)}{path_str}: {status_str}")

    asyncio.run(_check())


@cli.command()
def models():
    """List detected local Ollama models, dynamic selection, and API providers."""
    from .core.registry import CapabilityRegistry
    from .core.capabilities import CapabilityStatus

    config = load_config()
    registry = CapabilityRegistry(config=config)

    click.echo(click.style("Configured Fallback Chain (config):", bold=True))
    for idx, model in enumerate(config.models.fallback_chain, 1):
        click.echo(f"  {idx}. {model}")

    click.echo(click.style("\nLocal Ollama Service & Models:", bold=True))

    async def _check_models():
        caps = await registry.discover_all(test_harness_usability=False)
        ollama_cap = caps.get("ollama")

        if ollama_cap and ollama_cap.status == CapabilityStatus.READY:
            click.echo(f"  Status: {click.style('Running & Responding', fg='green')} at {config.models.ollama_base_url}")
            click.echo(f"  Auto-selected Model: {click.style(ollama_cap.selected_model or 'None', fg='cyan', bold=True)}")
            click.echo("  Installed Models:")
            for m in ollama_cap.available_models:
                marker = "★" if m == ollama_cap.selected_model else "✓"
                click.echo(f"    {marker} {m}")
        else:
            msg = ollama_cap.status_message if ollama_cap else "Not available"
            click.echo(f"  Status: {click.style(msg, fg='yellow')}")

        click.echo(click.style("\nRemote API Providers:", bold=True))
        api_caps = [c for c in caps.values() if c.execution_type.value == "direct_model" and c.name != "ollama"]
        for a in api_caps:
            if a.status == CapabilityStatus.READY:
                status_str = click.style(a.status_message, fg="green")
            else:
                status_str = click.style(a.status_message, fg="yellow")
            click.echo(f"  • {click.style(a.display_name, bold=True)}: {status_str}")

    asyncio.run(_check_models())


@cli.command()
def doctor():
    """Comprehensive system diagnosis for models, harnesses, and credentials."""
    from .core.registry import CapabilityRegistry
    from .core.capabilities import CapabilityStatus

    config = load_config()
    registry = CapabilityRegistry(config=config)

    click.echo(click.style("=== Emiliano Diagnostic Doctor ===", bold=True, fg="cyan"))
    click.echo(f"Platform: {sys.platform} | Python: {sys.version.split()[0]}")
    click.echo(f"Default Execution Policy: {config.execution_policy}")

    async def _diagnose():
        click.echo("\nDiscovering capabilities...")
        caps = await registry.discover_all(test_harness_usability=True)

        click.echo("\n" + click.style("[Direct Model Providers]", bold=True))
        for c in caps.values():
            if c.execution_type.value == "direct_model":
                color = "green" if c.is_usable else ("yellow" if c.status == CapabilityStatus.UNAUTHENTICATED else "red")
                click.echo(f"  • {c.display_name:20}: {click.style(c.status.value.upper(), fg=color):18} | {c.status_message}")

        click.echo("\n" + click.style("[External Agent Harnesses]", bold=True))
        for c in caps.values():
            if c.execution_type.value == "agent_harness":
                color = "green" if c.is_usable else ("yellow" if c.status == CapabilityStatus.UNAUTHENTICATED else "red")
                click.echo(f"  • {c.display_name:20}: {click.style(c.status.value.upper(), fg=color):18} | {c.status_message}")

        usable = [c for c in caps.values() if c.is_usable]
        click.echo("\n" + click.style(f"Summary: {len(usable)} of {len(caps)} capabilities ready for execution.", bold=True))
        if usable:
            click.echo("Ready routes: " + ", ".join([u.display_name for u in usable]))
        else:
            click.echo(click.style("Warning: No execution routes are currently ready. Check above diagnostics.", fg="yellow"))

    asyncio.run(_diagnose())


@cli.command()
@click.argument("goal")
@click.option("--policy", "-p", default="auto", type=click.Choice(["auto", "local", "harness", "api"], case_sensitive=False), help="Execution routing policy")
@click.option("--harness", default=None, help="Explicitly select an external agent harness (claude, codex, agy, opencode)")
@click.option("--provider", default=None, help="Explicitly select a direct provider (ollama, anthropic, openai, deepseek, gemini)")
@click.option("--model", "-m", default=None, help="Override model name")
@click.option("--timeout", default=180.0, type=float, help="Task execution timeout in seconds")
def run(goal: str, policy: str, harness: Optional[str], provider: Optional[str], model: Optional[str], timeout: float):
    """Execute a task directly from the command line using intelligent routing."""
    from .core.dispatcher import ExecutionDispatcher

    # Silence internal diagnostic logs in clean CLI mode
    try:
        from loguru import logger
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
    except ImportError:
        pass

    click.echo(click.style(f"Goal: {goal}", bold=True))

    def _on_route(cap):
        model_info = f" (model: {cap.selected_model})" if cap.selected_model else ""
        click.echo(click.style(f"[Emiliano] Routing to {cap.display_name}{model_info} via {cap.execution_type.value}...", fg="cyan"))

    def _on_chunk(chunk: str):
        click.echo(chunk, nl=False)

    def _on_reasoning(chunk: str):
        click.echo(click.style(chunk, dim=True, fg="bright_black"), nl=False)

    async def _execute():
        try:
            cap, full_output = await dispatcher.execute_task(
                goal=goal,
                policy=policy,
                harness_override=harness,
                provider_override=provider,
                model_override=model,
                on_chunk=_on_chunk,
                on_reasoning=_on_reasoning,
                on_route_selected=_on_route,
                timeout=timeout,
            )
            click.echo()
            click.echo(click.style(f"\n[Emiliano] Completed successfully via {cap.display_name}.", fg="green"))
        except (KeyboardInterrupt, asyncio.CancelledError):
            click.echo(click.style("\n[Emiliano] Interrupted by user (Ctrl+C).", fg="yellow"))
            sys.exit(130)
        except Exception as e:
            click.echo(click.style(f"\n[Emiliano Error] {e}", fg="red"), err=True)
            sys.exit(1)

    asyncio.run(_execute())


@cli.command()
@click.option("--policy", "-p", default="auto", type=click.Choice(["auto", "local", "harness", "api"], case_sensitive=False), help="Initial execution routing policy")
@click.option("--harness", default=None, help="Explicitly select an external agent harness (claude, codex, agy, opencode)")
@click.option("--provider", default=None, help="Explicitly select a direct provider (ollama, anthropic, openai, deepseek, gemini)")
@click.option("--model", "-m", default=None, help="Override model name")
@click.option("--timeout", default=180.0, type=float, help="Turn execution timeout in seconds")
def chat(policy: str, harness: Optional[str], provider: Optional[str], model: Optional[str], timeout: float):
    """Start an interactive terminal coworking session with Emiliano."""
    from .core.dispatcher import ExecutionDispatcher

    dispatcher = ExecutionDispatcher()

    # Silence internal diagnostic logs in interactive chat mode
    try:
        from loguru import logger
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
    except ImportError:
        pass







    menu_style = Style.from_dict({
        "completion-menu.completion": "bg:#1e293b #38bdf8",
        "completion-menu.completion.current": "bg:#0284c7 #ffffff bold",
        "completion-menu.meta": "bg:#0f172a #94a3b8",
        "completion-menu.meta.current": "bg:#0369a1 #ffffff bold",
        "scrollbar.background": "bg:#1e293b",
        "scrollbar.button": "bg:#38bdf8",
    }) if PROMPT_TOOLKIT_AVAILABLE else None

    prompt_session = None
    prompt_error = None
    if PROMPT_TOOLKIT_AVAILABLE:
        try:
            history_dir = os.path.expanduser("~/.emiliano")
            os.makedirs(history_dir, exist_ok=True)
            prompt_session = PromptSession(
                completer=SlashCommandCompleter(),
                complete_while_typing=True,
                history=FileHistory(os.path.join(history_dir, "history")),
                style=menu_style,
            )
        except Exception as e:
            prompt_session = None
            prompt_error = e

    click.echo(click.style("╔══════════════════════════════════════════════════════════════╗", fg="cyan"))
    click.echo(click.style("║         Emiliano Autonomous Terminal Coworker (v0.1)         ║", fg="cyan", bold=True))
    click.echo(click.style("║   Type your goal or question. Type / for slash commands.      ║", fg="cyan"))
    click.echo(click.style("║   Type 'exit' or 'quit' to quit.                             ║", fg="cyan"))
    click.echo(click.style("╚══════════════════════════════════════════════════════════════╝", fg="cyan"))
    if prompt_session is None:
        if os.environ.get("MSYSTEM") or os.environ.get("TERM_PROGRAM") == "mintty":
            click.echo(click.style("  [Tip] In Git Bash (MinTTY), run 'winpty emiliano' to enable slash command autocomplete.", fg="yellow"))

    active_policy = policy
    active_harness = harness
    active_provider = provider
    active_model = model

    conversation_history = [
        {"role": "system", "content": "You are Emiliano, an expert autonomous coding and execution engine."},
    ]

    last_ctrl_c = 0.0
    while True:
        target_desc = active_harness or active_provider or active_model or active_policy
        prompt_label = click.style(f"emiliano [{target_desc}]", fg="cyan", bold=True) + "> "
        try:
            if prompt_session:
                user_input = prompt_session.prompt(f"emiliano [{target_desc}]> ").strip()
            else:
                user_input = input(prompt_label).strip()
            last_ctrl_c = 0.0
        except KeyboardInterrupt:
            now = time.time()
            if now - last_ctrl_c < 1.5:
                click.echo(click.style("\nExiting Emiliano. Goodbye!", fg="yellow"))
                break
            last_ctrl_c = now
            click.echo(click.style("\n(Press Ctrl+C again or type 'exit' to quit)", fg="yellow"))
            continue
        except EOFError:
            click.echo(click.style("\nExiting Emiliano. Goodbye!", fg="yellow"))
            break

        if not user_input:
            continue

        cmd_lower = user_input.lower().strip()
        if cmd_lower in ("exit", "quit", "/exit", "/quit"):
            click.echo(click.style("Exiting Emiliano. Goodbye!", fg="yellow"))
            break

        if cmd_lower in ("/help", "help"):
            click.echo(click.style("\nAvailable Slash Commands in Chat:", bold=True))
            click.echo("  • /switch <target> : Lock to harness or provider (claude, codex, agy, opencode, ollama, auto)")
            click.echo("  • /policy <p>      : Switch routing policy (auto, local, harness, api)")
            click.echo("  • /model <name>    : Override model name (e.g. /model qwen3.5:2b)")
            click.echo("  • /clear           : Clear conversation history")
            click.echo("  • /history         : Show conversation turn count")
            click.echo("  • /doctor          : Run diagnostic check")
            click.echo("  • /models          : List available models and providers")
            click.echo("  • /harnesses       : List external agent harnesses")
            click.echo("  • /exit, exit      : Exit interactive session\n")
            continue

        if cmd_lower in ("/clear", "clear"):
            conversation_history = [
                {"role": "system", "content": "You are Emiliano, an expert autonomous coding and execution engine."},
            ]
            click.echo(click.style("✓ Conversation history cleared.", fg="green"))
            continue

        if cmd_lower in ("/history", "history"):
            turns = [m for m in conversation_history if m["role"] != "system"]
            click.echo(click.style(f"Conversation history has {len(turns)} turns ({len(conversation_history)} messages total).", fg="cyan"))
            continue

        if cmd_lower.startswith("/policy") or cmd_lower.startswith("policy"):
            parts = user_input.split(maxsplit=1)
            if len(parts) > 1 and parts[1].lower() in ("auto", "local", "harness", "api"):
                active_policy = parts[1].lower()
                click.echo(click.style(f"✓ Routing policy set to: {active_policy}", fg="green"))
            else:
                click.echo(click.style("Usage: /policy <auto|local|harness|api>", fg="yellow"))
            continue

        if cmd_lower.startswith("/switch") or cmd_lower.startswith("switch"):
            parts = user_input.split(maxsplit=1)
            if len(parts) > 1:
                target = parts[1].strip().lower()
                if target in ("auto", "none", "reset"):
                    active_harness = None
                    active_provider = None
                    active_policy = "auto"
                    click.echo(click.style("✓ Reset to automatic routing.", fg="green"))
                elif target in ("claude", "claude_code", "codex", "agy", "antigravity", "opencode"):
                    active_harness = target
                    active_provider = None
                    click.echo(click.style(f"✓ Locked to harness: {active_harness}", fg="green", bold=True))
                elif target in ("ollama", "anthropic", "openai", "deepseek", "gemini"):
                    active_provider = target
                    active_harness = None
                    click.echo(click.style(f"✓ Locked to provider: {active_provider}", fg="green", bold=True))
                else:
                    click.echo(click.style(f"Unknown target '{target}'. Use claude, codex, agy, opencode, ollama, anthropic, openai, deepseek, gemini, or auto.", fg="yellow"))
            else:
                click.echo(click.style("Usage: /switch <harness|provider|auto>", fg="yellow"))
            continue

        if cmd_lower.startswith("/model") or cmd_lower.startswith("model"):
            parts = user_input.split(maxsplit=1)
            if len(parts) > 1:
                m_target = parts[1].strip()
                if m_target in ("none", "auto", "reset"):
                    active_model = None
                    click.echo(click.style("✓ Model override removed.", fg="green"))
                else:
                    active_model = m_target
                    click.echo(click.style(f"✓ Model override set to: {active_model}", fg="green"))
            else:
                click.echo(click.style("Usage: /model <model_name|auto>", fg="yellow"))
            continue

        if cmd_lower in ("/doctor", "doctor"):
            from click.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(doctor)
            click.echo(result.output)
            continue

        if cmd_lower in ("/models", "models"):
            from click.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(models)
            click.echo(result.output)
            continue

        if cmd_lower in ("/harnesses", "harnesses"):
            from click.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(harnesses)
            click.echo(result.output)
            continue

        conversation_history.append({"role": "user", "content": user_input})

        def _chat_route(cap):
            model_info = f" (model: {cap.selected_model})" if cap.selected_model else ""
            if getattr(cap, "execution_type", None) and cap.execution_type.value == "agent_harness":
                click.echo(click.style(f"[{cap.display_name}] ", fg="cyan", bold=True) + click.style("Inspecting workspace & analyzing files...\n", dim=True))
            else:
                click.echo(click.style(f"[{cap.display_name}{model_info}] ", fg="cyan", bold=True), nl=False)

        def _chat_chunk(chunk: str):
            click.echo(chunk, nl=False)

        def _chat_reasoning(chunk: str):
            click.echo(click.style(chunk, dim=True, fg="bright_black"), nl=False)

        async def _execute_turn():
            try:
                cap, reply = await dispatcher.execute_task(
                    goal=user_input,
                    policy=active_policy,
                    harness_override=active_harness,
                    provider_override=active_provider,
                    model_override=active_model,
                    messages=conversation_history,
                    on_chunk=_chat_chunk,
                    on_reasoning=_chat_reasoning,
                    on_route_selected=_chat_route,
                    timeout=timeout,
                )
                click.echo()
                conversation_history.append({"role": "assistant", "content": reply})
            except (KeyboardInterrupt, asyncio.CancelledError):
                click.echo(click.style("\n[Interrupted by user]", fg="yellow"))
                conversation_history.pop()
            except Exception as e:
                click.echo(click.style(f"\n[Error] {e}", fg="red"))
                conversation_history.pop()

        asyncio.run(_execute_turn())
        click.echo()


def main():
    cli()


if __name__ == "__main__":
    main()
