"""
Rates local models against this machine's hardware, so the dock can say which ones run well.

A model runs fast when it fits in GPU memory (VRAM). If it does not, Ollama keeps part of it in system RAM and
runs that part on the CPU: it still works, but replies come several times slower. Past what RAM can hold it does
not run at all. The rating is an estimate from the model's file size, not a benchmark.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional

FIT_GPU = "fits_gpu"   # fully in VRAM: fast
FIT_SLOW = "slow"      # split between VRAM and RAM (or CPU only): works, but slowly
FIT_TOO_BIG = "too_big"

MB = 1024 * 1024
GB = 1024 * MB

# Loading needs more than the file: the context window's KV cache and runtime buffers
_OVERHEAD_FACTOR = 1.15
_OVERHEAD_BYTES = 512 * MB
# Share of RAM a spilled model may use; the OS and other apps need the rest
_RAM_SHARE = 0.5

# Tool-capable models from the Ollama library worth suggesting, smallest first. Sizes are the default
# (4-bit) download, approximate.
SUGGESTED_MODELS = [
    ("qwen3:1.7b", 1.4, "Tiny and quick; fine for simple file lookups"),
    ("qwen2.5-coder:3b", 1.9, "Small coding model"),
    ("qwen3:4b", 2.5, "Best small all-rounder for tool use"),
    ("qwen2.5-coder:7b", 4.7, "Stronger at code"),
    ("llama3.1:8b", 4.9, "Solid general model with tool support"),
    ("qwen3:8b", 5.2, "Noticeably better at using tools"),
    ("qwen2.5-coder:14b", 9.0, "Strong coder; needs a big GPU"),
]


@dataclass
class Hardware:
    gpu_name: Optional[str]
    vram_bytes: int
    ram_bytes: int


def _nvidia_gpu() -> tuple[Optional[str], int]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, 0
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, 0
    # Several GPUs: Ollama uses the biggest first
    best_name, best_mb = None, 0
    for line in out.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            mb = int(float(mem.strip()))
        except ValueError:
            continue
        if mb > best_mb:
            best_name, best_mb = name.strip(), mb
    return best_name, best_mb * MB


def _total_ram() -> int:
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return 0
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0


@lru_cache(maxsize=1)
def detect_hardware() -> Hardware:
    """GPU and RAM of this machine; cached, since neither changes while the engine runs."""
    gpu_name, vram = _nvidia_gpu()
    return Hardware(gpu_name=gpu_name, vram_bytes=vram, ram_bytes=_total_ram())


def rate_fit(size_bytes: int, hw: Hardware) -> str:
    """fits_gpu, slow or too_big for a model whose file is size_bytes."""
    needed = size_bytes * _OVERHEAD_FACTOR + _OVERHEAD_BYTES
    if hw.vram_bytes and needed <= hw.vram_bytes:
        return FIT_GPU
    if needed <= hw.vram_bytes + hw.ram_bytes * _RAM_SHARE:
        return FIT_SLOW
    return FIT_TOO_BIG


def rate_installed(models: List[Dict], hw: Hardware) -> List[Dict]:
    """
    Adds fit and recommended to installed models ({name, sizeBytes, tools}). The recommended model is the biggest
    tool-capable one that fits the GPU, or failing that the smallest tool-capable one that runs at all.
    """
    rated = [{**m, "fit": rate_fit(m["sizeBytes"], hw), "recommended": False} for m in models]
    with_tools = [m for m in rated if m.get("tools")]
    fast = [m for m in with_tools if m["fit"] == FIT_GPU]
    slow = [m for m in with_tools if m["fit"] == FIT_SLOW]
    pick = (max(fast, key=lambda m: m["sizeBytes"]) if fast
            else min(slow, key=lambda m: m["sizeBytes"]) if slow else None)
    if pick:
        pick["recommended"] = True
    return rated


def suggest_downloads(installed: List[str], hw: Hardware) -> List[Dict]:
    """Suggested models not installed yet that run on this machine, fast ones first."""
    have = {name.split(":latest")[0] for name in installed}
    out = []
    for name, size_gb, note in SUGGESTED_MODELS:
        if name in have:
            continue
        fit = rate_fit(int(size_gb * GB), hw)
        if fit != FIT_TOO_BIG:
            out.append({"name": name, "sizeGb": size_gb, "fit": fit, "note": note, "pull": f"ollama pull {name}"})
    out.sort(key=lambda s: (s["fit"] != FIT_GPU, -s["sizeGb"] if s["fit"] == FIT_GPU else s["sizeGb"]))
    return out


def hardware_dict(hw: Hardware) -> Dict:
    return {"gpuName": hw.gpu_name, "vramBytes": hw.vram_bytes, "ramBytes": hw.ram_bytes}


async def local_model_report(mgr) -> Dict:
    """
    Installed local models rated for this machine, for the dock and the terminal: {hardware, models: [{name,
    sizeBytes, tools, fit, recommended, loaded, vramBytes}], suggestions}. mgr is an OllamaManager.
    """
    import asyncio

    hw = await asyncio.to_thread(detect_hardware)
    details, loaded = await asyncio.gather(mgr.list_model_details(), mgr.list_loaded())
    models = rate_installed(details, hw)
    for m in models:
        info = loaded.get(m["name"])
        m["loaded"] = info is not None
        m["vramBytes"] = info["vramBytes"] if info else 0
    return {
        "hardware": hardware_dict(hw),
        "models": models,
        "suggestions": suggest_downloads([m["name"] for m in details], hw),
    }


__all__ = ["FIT_GPU", "FIT_SLOW", "FIT_TOO_BIG", "Hardware", "detect_hardware", "rate_fit", "rate_installed",
           "suggest_downloads", "hardware_dict", "local_model_report"]
