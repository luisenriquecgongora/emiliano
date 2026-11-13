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
from . import __version__
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
        "/model": "Pick the model that answers: no name shows a numbered list rated for this machine",
        "/load": "Load a local model into memory now, so replies start at once",
        "/unload": "Free the memory a loaded local model holds",
        "/doctor": "Run diagnostic check of models, credentials, and harnesses",
        "/models": "List models, rated for this machine's GPU and RAM, plus suggested downloads",
        "/harnesses": "List external CLI agent harnesses and auth status",
        "/mcp": "Start the configured MCP servers and list their tools",
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

    def __init__(self):
        # Installed model names for /model, /load and /unload; filled once the chat has listed them
        self.model_names: list = []

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

        # 4. Model names for /model, /load and /unload
        for cmd in ("/model ", "/load ", "/unload "):
            if stripped.startswith(cmd):
                current_arg = stripped[len(cmd):]
                for name in self.model_names:
                    if name.lower().startswith(current_arg.lower()):
                        yield Completion(name, start_position=-len(current_arg), display=name)
                return


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="emiliano")
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

        if ollama_cap and ollama_cap.status == CapabilityStatus.READY:
            from .cli_models import format_local_report
            from .direct.hardware import local_model_report

            click.echo(click.style("\nFit for This Machine:", bold=True))
            for line in format_local_report(await local_model_report(registry.ollama_mgr)):
                click.echo(line)

        click.echo(click.style("\nRemote API Providers:", bold=True))
        api_caps = [c for c in caps.values() if c.execution_type.value == "direct_model" and c.name != "ollama"]
        for a in api_caps:
            if a.status == CapabilityStatus.READY:
                status_str = click.style(a.status_message, fg="green")
            else:
                status_str = click.style(a.status_message, fg="yellow")
            click.echo(f"  • {click.style(a.display_name, bold=True)}: {status_str}")

    asyncio.run(_check_models())


@cli.command(name="mcp")
def mcp_command():
    """Start the MCP servers in the config and list the tools each one offers."""
    from .mcp import McpManager

    config = load_config()
    if not config.mcp_servers:
        click.echo("No MCP servers configured. Add some to emiliano.yaml (or ~/.emiliano/config.yaml), e.g.:\n")
        click.echo("mcp_servers:\n  filesystem:\n    command: npx\n"
                   "    args: [\"-y\", \"@modelcontextprotocol/server-filesystem\", \".\"]\n"
                   "  plaatoos:\n    url: https://api-takient.onrender.com/mcp\n"
                   "    headers: {Authorization: \"Bearer ${PLAATOOS_TOKEN}\"}")
        return

    click.echo(click.style("MCP Servers:", bold=True))
    for name, cfg in config.mcp_servers.items():
        if not cfg.enabled:
            click.echo(f"  - {click.style(name, bold=True)}: {click.style('disabled', fg='yellow')}")
    manager = McpManager(config.mcp_servers, cwd=os.getcwd())
    try:
        click.echo(click.style("  Starting servers (the first npx run downloads the package)...", dim=True))
        manager.start()
        for status in manager.statuses.values():
            if status.ok:
                hidden = (f" ({status.hidden} hidden by tools / exclude_tools / allow_destructive)"
                          if status.hidden else "")
                click.echo(f"  ✓ {click.style(status.name, bold=True)}: "
                           f"{click.style(f'{len(status.tools)} tools', fg='green')}{hidden}")
            else:
                click.echo(f"  ✗ {click.style(status.name, bold=True)}: {click.style(status.error, fg='red')}")
        if manager.tools:
            click.echo(click.style("\nTools local and API models can call:", bold=True))
            for line in manager.describe_tools().splitlines():
                click.echo(f"  {line}")
    finally:
        manager.close()


@cli.command(name="connect")
@click.argument("service", type=click.Choice(["plaatoos"], case_sensitive=False))
@click.option("--token", default=None, help="Use an agent token (pak_...) instead of signing in with the browser")
def connect_command(service: str, token: Optional[str]):
    """Connect an MCP service (PlaatoOS) so models can use its tools."""
    from .mcp.connect import connect

    service = service.lower()
    if not token:
        click.echo(f"Opening your browser to sign in to {service}. Pick the business to connect and approve.")
    try:
        result = connect(service, token=token,
                         on_url=lambda url: click.echo(click.style(f"If the browser did not open, go to:\n  {url}",
                                                                   dim=True)))
    except Exception as e:
        click.echo(click.style(f"Could not connect {service}: {e}", fg="red"))
        sys.exit(1)
    click.echo(click.style(f"✓ Connected {service} ({result['auth']}); saved in {result['config']}", fg="green"))
    if result["ok"]:
        hidden = f" ({result['hidden']} hidden by filters)" if result["hidden"] else ""
        click.echo(f"  {result['tools']} tools available{hidden}. Run `emiliano mcp` to list them.")
    else:
        click.echo(click.style(f"  But its tools could not be loaded: {result['error']}", fg="yellow"))


@cli.command(name="disconnect")
@click.argument("service", type=click.Choice(["plaatoos"], case_sensitive=False))
def disconnect_command(service: str):
    """Sign out of an MCP service and remove it from the config."""
    from .mcp.connect import disconnect

    result = disconnect(service.lower())
    note = "signed out and credentials removed" if result["removed_credentials"] else "no stored credentials"
    click.echo(click.style(f"✓ Disconnected {service} ({note}); updated {result['config']}", fg="green"))


@cli.command(name="eval")
@click.argument("suites", nargs=-1)
@click.option("--target", "-t", default="ollama", show_default=True,
              help="What answers: ollama, ollama:<model>, anthropic:<model>, claude_code, codex, opencode, ...")
@click.option("--timeout", default=180.0, type=float, show_default=True, help="Seconds per task")
@click.option("--repeat", "-r", default=1, type=click.IntRange(1, 50), show_default=True,
              help="Run each model task this many times; a small model's single run varies a lot")
@click.option("--reasoning", type=click.Choice(["auto", "on", "off"]), default="auto", show_default=True,
              help="Force a local model's reasoning on/off (auto: off for conversation, as in normal use)")
@click.option("--list", "list_only", is_flag=True, help="List the built-in suites and exit")
def eval_command(suites: tuple, target: str, timeout: float, repeat: int, reasoning: str, list_only: bool):
    """Run eval suites (default: all built-in) against a target and save a JSON report."""
    from loguru import logger

    from .evals.runner import EvalRunner, Target, list_suites, load_suite, save_report

    logger.remove()  # per-task INFO lines would bury the results table
    logger.add(sys.stderr, level="WARNING")

    if list_only:
        for name in list_suites():
            suite = load_suite(name)
            click.echo(f"  {click.style(name, bold=True):<28} {len(suite.get('tasks', []))} tasks  {suite.get('description', '')}")
        return

    parsed = Target.parse(target)
    parsed.reasoning = {"auto": None, "on": True, "off": False}[reasoning]
    runner = EvalRunner(timeout=timeout)
    marks = {"passed": ("PASS", "green"), "failed": ("FAIL", "red"), "flaky": ("FLKY", "yellow"),
             "error": ("ERR ", "red"), "skipped": ("SKIP", "yellow")}

    def show(result):
        label, color = marks[result.status]
        timing = f"{result.duration_s}s" if result.duration_s is not None else ""
        speed = f" {result.tokens_per_second} tok/s" if result.tokens_per_second else ""
        count = f" {result.passes}/{result.runs}" if result.runs > 1 else ""
        click.echo(f"  {click.style(label, fg=color)}{count} {result.id:<22} {timing:>8}{speed}  {result.detail}")
        if result.status in ("failed", "flaky") and result.output:
            click.echo(click.style(f"       reply: {result.output[:160]!r}", dim=True))

    for name in suites or list_suites():
        suite = load_suite(name)
        settings = "".join([f", reasoning {reasoning}" if reasoning != "auto" else "", f", x{repeat}" if repeat > 1 else ""])
        click.echo(click.style(f"\n{suite['name']} → {parsed.spec}{settings}", bold=True))
        report = asyncio.run(runner.run_suite(suite, parsed, on_result=show, repeat=repeat))
        if reasoning != "auto":
            report.target += f" reasoning={reasoning}"  # kept apart in saved reports and file names
        s = report.to_dict()["summary"]
        rate = "-" if s["pass_rate"] is None else f"{s['pass_rate']:.0%}"
        click.echo(f"  {s['passed']} passed, {s['flaky']} flaky, {s['failed']} failed, {s['errors']} errors, {s['skipped']} skipped "
                   f"→ {click.style(rate, bold=True)}"
                   + (f" | median first output {s['median_first_output_s']}s" if s["median_first_output_s"] else "")
                   + (f" | median {s['median_tokens_per_second']} tok/s" if s["median_tokens_per_second"] else ""))
        click.echo(f"  Report: {save_report(report)}")


@cli.command()
@click.option("--last", "-n", default=20, type=int, help="How many recent tasks to show")
@click.option("--json", "as_json", is_flag=True, help="Print full trace records as JSON")
def traces(last: int, as_json: bool):
    """Show recent task traces: route, time to first output, duration, tokens/s."""
    import json

    from .core.traces import TraceStore

    rows = TraceStore().recent(last)
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    if not rows:
        click.echo("No traces yet. Run a task first (traces are on unless 'traces: false' is set in the config).")
        return

    def fmt(value, suffix=""):
        return "-" if value is None else f"{value}{suffix}"

    colors = {"succeeded": "green", "failed": "red", "cancelled": "yellow"}
    click.echo(click.style(f"{'when':<17} {'outcome':<10} {'route':<24} {'first':>7} {'total':>8} {'tok/s':>7}  goal",
                           bold=True))
    for r in rows:
        route = r["model"] or r["route"] or "-"
        tried = len(r["attempts"])
        if tried > 1:
            route += f" (+{tried - 1} failed)"
        click.echo(
            f"{r['started_at'][:16].replace('T', ' '):<17} "
            f"{click.style(r['outcome'].ljust(10), fg=colors.get(r['outcome']))} "
            f"{route[:24]:<24} {fmt(r['first_output_s'], 's'):>7} {fmt(r['duration_s'], 's'):>8} "
            f"{fmt(r['tokens_per_second']):>7}  {r['goal'][:50].replace(chr(10), ' ')}"
        )


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
@click.option("--policy", "-p", default=None, type=click.Choice(["auto", "local", "harness", "api"], case_sensitive=False), help="Execution routing policy (default: execution_policy from config, else auto)")
@click.option("--harness", default=None, help="Explicitly select an external agent harness (claude, codex, agy, opencode)")
@click.option("--provider", default=None, help="Explicitly select a direct provider (ollama, anthropic, openai, deepseek, gemini)")
@click.option("--model", "-m", default=None, help="Override model name")
@click.option("--timeout", default=300.0, type=float, help="Task execution timeout in seconds")
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

    dispatcher = ExecutionDispatcher()

    click.echo(click.style(f"Goal: {goal}", bold=True))

    def _on_route(cap):
        model_info = f" (model: {cap.selected_model})" if cap.selected_model else ""
        click.echo(click.style(f"[Emiliano] Routing to {cap.display_name}{model_info} via {cap.execution_type.value}...", fg="cyan"))

    def _on_chunk(chunk: str):
        click.echo(chunk, nl=False)

    def _on_reasoning(chunk: str):
        click.echo(click.style(chunk, dim=True, fg="bright_black"), nl=False)

    async def _execute():
        # Ollama loads the model in its own process while this one routes the request. Not litellm: importing
        # it alongside held the GIL and slowed routing from 9 s to 44 s (local calls do not need it).
        prewarm = asyncio.create_task(dispatcher.prewarm_local(policy, harness, provider, model, import_litellm=False))
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
        finally:
            prewarm.cancel()

    asyncio.run(_execute())


@cli.command()
@click.option("--policy", "-p", default=None, type=click.Choice(["auto", "local", "harness", "api"], case_sensitive=False), help="Initial execution routing policy (default: execution_policy from config, else auto)")
@click.option("--harness", default=None, help="Explicitly select an external agent harness (claude, codex, agy, opencode)")
@click.option("--provider", default=None, help="Explicitly select a direct provider (ollama, anthropic, openai, deepseek, gemini)")
@click.option("--model", "-m", default=None, help="Override model name")
@click.option("--timeout", default=300.0, type=float, help="Turn execution timeout in seconds")
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

    # While the user types the first message: discover routes and have Ollama load the model (~25 s cold).
    # Not litellm: importing it here would hold the GIL for ~13 s and make typing lag.
    import threading
    threading.Thread(
        target=lambda: asyncio.run(dispatcher.warm_up(policy, harness, provider, model, import_litellm=False)),
        name="emiliano-warm-up", daemon=True,
    ).start()







    menu_style = Style.from_dict({
        "completion-menu.completion": "bg:#1e293b #38bdf8",
        "completion-menu.completion.current": "bg:#0284c7 #ffffff bold",
        "completion-menu.meta": "bg:#0f172a #94a3b8",
        "completion-menu.meta.current": "bg:#0369a1 #ffffff bold",
        "scrollbar.background": "bg:#1e293b",
        "scrollbar.button": "bg:#38bdf8",
    }) if PROMPT_TOOLKIT_AVAILABLE else None

    prompt_session = None
    completer = SlashCommandCompleter()
    # prompt_toolkit needs a real terminal; with piped input it swallows lines, so fall back to input()
    if PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
        try:
            history_dir = os.path.expanduser("~/.emiliano")
            os.makedirs(history_dir, exist_ok=True)
            prompt_session = PromptSession(
                completer=completer,
                complete_while_typing=True,
                history=FileHistory(os.path.join(history_dir, "history")),
                style=menu_style,
            )
        except Exception:
            prompt_session = None

    click.echo(click.style("╔══════════════════════════════════════════════════════════════╗", fg="cyan"))
    click.echo(click.style("║         Emiliano Autonomous Terminal Coworker (v0.1)         ║", fg="cyan", bold=True))
    click.echo(click.style("║   Type your goal or question. Type / for slash commands.      ║", fg="cyan"))
    click.echo(click.style("║   Type 'exit' or 'quit' to quit.                             ║", fg="cyan"))
    click.echo(click.style("╚══════════════════════════════════════════════════════════════╝", fg="cyan"))
    if prompt_session is None:
        if os.environ.get("MSYSTEM") or os.environ.get("TERM_PROGRAM") == "mintty":
            click.echo(click.style("  [Tip] In Git Bash (MinTTY), run 'winpty emiliano' to enable slash command autocomplete.", fg="yellow"))

    active_policy = policy or dispatcher.config.execution_policy or "auto"
    active_harness = harness
    active_provider = provider
    active_model = model
    picked_provider = False  # True when /model set active_provider, so "/model auto" clears it too

    from .cli_models import model_choices, resolve_pick, split_command
    from .direct.hardware import local_model_report

    def ask(question: str) -> str:
        try:
            return (prompt_session.prompt(question) if prompt_session else input(question)).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def load_choices():
        """Numbered /model choices plus the local report; also refreshes name completion."""
        async def _gather():
            caps = await dispatcher.registry.discover_all(test_harness_usability=False)
            report = None
            if caps.get("ollama") and caps["ollama"].is_usable:
                report = await local_model_report(dispatcher.registry.ollama_mgr)
            return caps, report
        caps, report = asyncio.run(_gather())
        choices = model_choices(caps, report)
        completer.model_names = [c["model"] for c in choices]
        return choices, report

    conversation_history = [
        {"role": "system", "content": "You are Emiliano, an expert autonomous coding and execution engine."},
    ]

    last_ctrl_c = 0.0
    while True:
        target_desc = active_harness or (f"{active_provider}/{active_model}" if active_provider and active_model
                                         else active_provider or active_model or active_policy)
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
            click.echo("  • /model [name|n]  : Pick the model; no name shows a numbered list rated for this machine")
            click.echo("  • /load [name]     : Keep a local model in memory (default: the recommended one)")
            click.echo("  • /unload [name]   : Free a loaded local model's memory (default: all loaded)")
            click.echo("  • /clear           : Clear conversation history")
            click.echo("  • /history         : Show conversation turn count")
            click.echo("  • /doctor          : Run diagnostic check")
            click.echo("  • /models          : List available models and providers")
            click.echo("  • /harnesses       : List external agent harnesses")
            click.echo("  • /mcp             : List MCP servers and the tools they give the models")
            click.echo("  • /context         : Show context window usage (Phase 1)")
            click.echo("  • /compact         : Compact conversation history (Phase 1)")
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

        if cmd_lower in ("/context", "context"):
            # Display context usage metrics
            try:
                # Get the current model being used (from active settings)
                model_id = active_model or dispatcher.config.models.remote_model
                if active_provider:
                    model_id = f"{active_provider}/{model_id.split('/')[-1]}"

                # Collect metrics
                metrics = dispatcher.context_manager.get_metrics(
                    messages=conversation_history,
                    model_id=model_id,
                )

                # Format and display
                formatted = dispatcher.context_manager.metrics_collector.format_metrics(
                    metrics,
                    model_name=model_id,
                )
                click.echo(formatted)
            except Exception as e:
                click.echo(click.style(f"Error displaying context: {e}", fg="red"))
            continue

        if cmd_lower in ("/compact", "compact"):
            # Manually trigger conversation summarization
            click.echo(click.style("⚙️  Compacting conversation history...", fg="cyan"))
            try:
                compacted, summary = asyncio.run(
                    dispatcher.context_manager.compact_conversation(conversation_history)
                )
                conversation_history = compacted
                click.echo(click.style(f"✓ Conversation compacted: {len(conversation_history)} messages remaining", fg="green"))
                click.echo(click.style("\nSummary of previous conversation:", fg="cyan", bold=True))
                click.echo(summary[:500] + ("..." if len(summary) > 500 else ""))
            except Exception as e:
                click.echo(click.style(f"Error compacting conversation: {e}", fg="red"))
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

        cmd_word, cmd_arg = split_command(user_input)

        if cmd_word in ("/model", "model"):
            if cmd_arg.lower() in ("none", "auto", "reset"):
                active_model = None
                if picked_provider:
                    active_provider, picked_provider = None, False
                click.echo(click.style("✓ Model override removed.", fg="green"))
                continue
            try:
                choices, _ = load_choices()
            except Exception as e:
                choices = []
                click.echo(click.style(f"Could not list models: {e}", fg="yellow"))
            if not cmd_arg:
                if not choices:
                    click.echo(click.style("No models found. Install one with 'ollama pull qwen3:4b'.", fg="yellow"))
                    continue
                click.echo(click.style("\nModels you can pick:", bold=True))
                for idx, choice in enumerate(choices, 1):
                    click.echo(f"  {idx:>2}. {choice['label']}")
                click.echo("   0. Default (let routing decide)")
                cmd_arg = ask("Pick a number (Enter to cancel): ")
                if not cmd_arg:
                    continue
                if cmd_arg == "0":
                    active_model = None
                    if picked_provider:
                        active_provider, picked_provider = None, False
                    click.echo(click.style("✓ Model override removed.", fg="green"))
                    continue
            picked = resolve_pick(choices, cmd_arg)
            if picked:
                active_provider, active_model, active_harness = picked["provider"], picked["model"], None
                picked_provider = True
                click.echo(click.style(f"✓ Replies now come from {active_provider}/{active_model}", fg="green"))
            elif cmd_arg.isdigit():
                click.echo(click.style(f"No model number {cmd_arg}. Type /model to see the list.", fg="yellow"))
            else:
                # A name that is not listed: keep the old behaviour of overriding the model name only
                active_model = cmd_arg
                click.echo(click.style(f"✓ Model override set to: {active_model}", fg="green"))
            continue

        if cmd_word in ("/load", "/unload"):
            mgr = dispatcher.registry.ollama_mgr
            try:
                report = asyncio.run(local_model_report(mgr))
            except Exception as e:
                click.echo(click.style(f"Could not reach Ollama: {e}", fg="yellow"))
                continue
            local = report["models"]
            local_names = [m["name"] for m in local]
            completer.model_names = local_names
            if cmd_word == "/load":
                if cmd_arg:
                    target = resolve_pick([{"provider": "ollama", "model": n} for n in local_names], cmd_arg)
                    name = target["model"] if target else None
                else:
                    # The model picked with /model, else the one recommended for this machine
                    name = active_model if active_model in local_names else next(
                        (m["name"] for m in local if m["recommended"]), None)
                if not name:
                    click.echo(click.style(f"Not an installed local model: {cmd_arg or '(none)'}. See /models.",
                                           fg="yellow"))
                    continue
                click.echo(click.style(f"Loading {name} (can take ~20 s)...", dim=True))
                ok = asyncio.run(mgr.preload(name, num_ctx=dispatcher.config.models.ollama_num_ctx, keep_alive=-1))
                click.echo(click.style(f"✓ {name} is in memory until you /unload it." if ok
                                       else f"Ollama could not load {name}.", fg="green" if ok else "red"))
            else:
                names = [cmd_arg] if cmd_arg else [m["name"] for m in local if m["loaded"]]
                if not names:
                    click.echo(click.style("No local models are loaded.", fg="cyan"))
                    continue
                for name in names:
                    ok = asyncio.run(mgr.unload(name))
                    click.echo(click.style(f"✓ Unloaded {name}." if ok else f"Ollama could not unload {name}.",
                                           fg="green" if ok else "red"))
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

        if cmd_lower == "/mcp":
            from click.testing import CliRunner
            click.echo(CliRunner().invoke(mcp_command).output)
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
