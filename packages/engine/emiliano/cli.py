"""
Command-line Interface for Emiliano.
Allows launching the daemon server or running standalone tasks directly in terminal.
"""

from __future__ import annotations

import asyncio
import shutil
import click
from .core.config import load_config
from .core.single_instance import SingleInstanceGuard
from .direct.client import UnifiedLLMClient


@click.group()
def cli():
    """Emiliano: Unified Meta-Harness & Desktop Cowork Platform."""
    pass


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
    """Check availability of external agent harnesses on system PATH."""
    config = load_config()
    items = [
        ("Claude Code", config.harnesses.claude_code_cmd),
        ("Antigravity (AGY)", config.harnesses.antigravity_cmd),
        ("OpenCode", config.harnesses.opencode_cmd),
        ("Codex", config.harnesses.codex_cmd),
    ]
    click.echo("External Harness Status:")
    for name, cmd in items:
        path = shutil.which(cmd)
        status = click.style(f"Found ({path})", fg="green") if path else click.style("Not Found in PATH", fg="yellow")
        click.echo(f"  • {name} [{cmd}]: {status}")


@cli.command()
def models():
    """List detected local Ollama models and fallback chain."""
    config = load_config()
    client = UnifiedLLMClient(ollama_base_url=config.models.ollama_base_url)

    click.echo("Configured Model Fallback Chain:")
    for idx, model in enumerate(config.models.fallback_chain, 1):
        click.echo(f"  {idx}. {model}")

    click.echo("\nChecking Local Ollama Models...")
    try:
        local_models = asyncio.run(client.list_local_ollama_models())
        if local_models:
            for m in local_models:
                click.echo(f"  ✓ {m}")
        else:
            click.echo(click.style("  No local models detected (or Ollama not running)", fg="yellow"))
    except Exception as e:
        click.echo(click.style(f"  Error checking Ollama: {e}", fg="red"))


@cli.command()
@click.argument("goal")
@click.option("--model", default=None, help="Override model name")
def run(goal: str, model: str):
    """Execute a task directly from the command line."""
    config = load_config()
    client = UnifiedLLMClient(
        ollama_base_url=config.models.ollama_base_url,
        fallback_chain=config.models.fallback_chain
    )
    click.echo(click.style(f"Goal: {goal}", bold=True))
    messages = [
        {"role": "system", "content": "You are Emiliano, an expert autonomous coding and execution engine."},
        {"role": "user", "content": goal}
    ]

    async def _execute():
        async for chunk in client.stream_completion(messages, model_name=model):
            click.echo(chunk, nl=False)
        click.echo()

    asyncio.run(_execute())


def main():
    cli()


if __name__ == "__main__":
    main()
