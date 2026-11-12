"""
Terminal side of model picking: the hardware report behind `/models`, the numbered list behind `/model`, and
resolving what the user typed after `/model`, `/load` or `/unload`. Plain functions so they can be tested
without a terminal; cli.py does the printing and prompting.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

FIT_ICONS = {"fits_gpu": "✅", "slow": "⚠️", "too_big": "❌"}
FIT_TEXT = {"fits_gpu": "fits your GPU: fast", "slow": "spills into RAM: slow", "too_big": "too big for this machine"}


def split_command(user_input: str) -> Tuple[str, str]:
    """("/model", "qwen3:4b") from "/model qwen3:4b". Matches whole words, so "/models" is not "/model"."""
    parts = user_input.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0].lower(), parts[1].strip() if len(parts) > 1 else ""


def format_gb(size_bytes: int) -> str:
    return f"{size_bytes / 1024 ** 3:.1f} GB"


def describe_model(m: Dict) -> str:
    """'✅ qwen3.5:2b  2.6 GB · fits your GPU: fast · uses file tools · in memory  ★ recommended'"""
    tools = {True: "uses file tools", False: "no tool support", None: "tool support unknown"}[m.get("tools")]
    parts = [format_gb(m["sizeBytes"]), FIT_TEXT[m["fit"]], tools]
    if m.get("loaded"):
        parts.append(f"in memory ({format_gb(m.get('vramBytes', 0))} on GPU)")
    text = f"{FIT_ICONS[m['fit']]} {m['name']}  " + " · ".join(parts)
    return text + ("  ★ recommended" if m.get("recommended") else "")


def format_local_report(report: Dict) -> List[str]:
    """The lines `/models` prints about this machine: hardware, rated local models, suggested downloads."""
    hw = report["hardware"]
    gpu = f"{hw['gpuName']}, {format_gb(hw['vramBytes'])} VRAM" if hw.get("gpuName") else "No NVIDIA GPU found"
    lines = [f"  This machine: {gpu} · {format_gb(hw['ramBytes'])} RAM"]
    if report["models"]:
        lines += [f"    {describe_model(m)}" for m in report["models"]]
    else:
        lines.append("    No local models installed.")
    if report["suggestions"]:
        lines.append("  Suggested downloads for this machine (run the command in a terminal):")
        lines += [f"    {FIT_ICONS[s['fit']]} {s['pull']:<28} ~{s['sizeGb']} GB · {s['note']}"
                  for s in report["suggestions"]]
    lines.append("  Ratings are estimates from file size. /model picks one, /load and /unload manage memory.")
    return lines


def model_choices(caps: Dict, report: Optional[Dict]) -> List[Dict]:
    """
    Everything `/model` can pick, numbered in this order: local models (recommended first), then models of ready
    API providers. Each is {provider, model, label}.
    """
    from .core.capabilities import CapabilityStatus, ExecutionType

    choices: List[Dict] = []
    local = sorted((report or {}).get("models", []), key=lambda m: not m.get("recommended"))
    for m in local:
        choices.append({"provider": "ollama", "model": m["name"], "label": describe_model(m)})
    if not local and caps.get("ollama") and caps["ollama"].status == CapabilityStatus.READY:
        choices += [{"provider": "ollama", "model": name, "label": name} for name in caps["ollama"].available_models]
    for cap in caps.values():
        if (cap.name != "ollama" and cap.execution_type == ExecutionType.DIRECT_MODEL
                and cap.status == CapabilityStatus.READY):
            choices += [{"provider": cap.name, "model": name, "label": f"{name}  ({cap.display_name})"}
                        for name in cap.available_models]
    return choices


def resolve_pick(choices: List[Dict], arg: str) -> Optional[Dict]:
    """The choice for a list number ("2") or an exact model name; None when it is neither."""
    arg = arg.strip()
    if arg.isdigit():
        index = int(arg) - 1
        return choices[index] if 0 <= index < len(choices) else None
    for choice in choices:
        if choice["model"].lower() == arg.lower() or f"{choice['provider']}/{choice['model']}".lower() == arg.lower():
            return choice
    return None
