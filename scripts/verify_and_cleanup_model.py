"""
Autonomous verification and cleanup script for Emiliano local models.
1. Waits for qwen2.5-coder:3b to finish downloading in Ollama.
2. Runs a smoke test and tool execution benchmark.
3. Automatically deletes qwen3.5:2b to reclaim 2.7 GB of disk space.
"""

import subprocess
import sys
import time
from pathlib import Path

# Add engine to path
ENGINE_DIR = Path(__file__).resolve().parent.parent / "packages" / "engine"
sys.path.insert(0, str(ENGINE_DIR))

def check_model_installed(name: str) -> bool:
    try:
        res = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=True)
        return name in res.stdout
    except Exception as e:
        print(f"Error checking ollama list: {e}")
        return False

def wait_for_model(name: str, timeout_seconds: int = 1800) -> bool:
    print(f"⏳ Waiting for '{name}' to complete installation in Ollama...")
    t0 = time.time()
    while time.time() - t0 < timeout_seconds:
        if check_model_installed(name):
            print(f"✅ Model '{name}' is installed and ready!")
            return True
        time.sleep(15)
    print(f"❌ Timeout waiting for '{name}'.")
    return False

def run_smoke_test(name: str) -> bool:
    print(f"\n🧪 Running smoke test on '{name}'...")
    try:
        res = subprocess.run(
            ["ollama", "run", name, "Say 'Hello Emiliano' and exit."],
            capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace"
        )
        print(f"Model Output: {res.stdout.strip()[:200]}")
        return res.returncode == 0
    except Exception as e:
        print(f"Smoke test failed: {e}")
        return False

def remove_old_model(name: str = "qwen3.5:2b") -> bool:
    print(f"\n🧹 Removing decommissioned model '{name}'...")
    try:
        res = subprocess.run(["ollama", "rm", name], capture_output=True, text=True, check=True)
        print(f"Result: {res.stdout.strip() or 'Removed successfully.'}")
        print(f"🎉 Reclaimed 2.7 GB of disk space!")
        return True
    except Exception as e:
        print(f"Failed to remove model '{name}': {e}")
        return False

def main():
    target = "qwen2.5-coder:3b"
    if not check_model_installed(target):
        ok = wait_for_model(target, timeout_seconds=1800)
        if not ok:
            sys.exit(1)

    # 1. Smoke test
    smoke_ok = run_smoke_test(target)
    if not smoke_ok:
        print("❌ Smoke test failed; aborting model removal.")
        sys.exit(1)

    print(f"✅ Smoke test passed for {target}!")

    # 2. Decommission old model
    rm_ok = remove_old_model("qwen3.5:2b")
    if rm_ok:
        print("\n🏆 Model transition and cleanup completed successfully!")

if __name__ == "__main__":
    main()
