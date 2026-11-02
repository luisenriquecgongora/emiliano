# Emiliano

> *An autonomous desktop coworker and meta-harness for intelligent multi-agent orchestration.*

`emiliano` combines two complementary systems into a unified platform:
1. **The Meta-Harness & Direct Execution Engine (`packages/engine`)**: A supervisor that controls and delegates work to external agent harnesses (Claude Code, Antigravity, OpenCode, Codex, MCP) or directly executes tasks via local models (Ollama, vLLM) and remote frontier APIs (Claude 3.7, GPT-4.5, DeepSeek, Gemini).
2. **The Desktop Cowork UI (`apps/desktop`)**: A Tauri-based desktop coworker (the Python engine ships inside it) inspired by Anthropic's Claude Cowork, featuring a collapsible floating dock, non-blocking click-through transparent HUD overlay, and hybrid screen perception (Windows UI Automation + Multimodal Vision).

---

## Comparison Matrix: Emiliano vs. Other Harnesses

| Capability / Dimension | **Emiliano** | **Claude Cowork** | **Claude Code** | **Antigravity (AGY)** | **OpenHands** | **Aider** | **Goose** | **Raven** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Harness Architecture** | **Meta-Harness + Direct Engine** | Single Agent Coworker | Single CLI Agent | Single CLI & IDE Agent | Sandbox Web Agent | Git Pair Programmer | Extensible Desktop Agent | Meta-Harness (DAG RSI) |
| **Multi-Harness Orchestration**<br>*(Controls external CLI/API agents)* | **Yes**<br>*(Claude, AGY, OpenCode, Codex)* | No | No | No | No | No | No | **Yes**<br>*(Internal sub-agents)* |
| **OS Screen & GUI Manipulation**<br>*(Controls arbitrary desktop apps)* | **Yes**<br>*(Mouse, Keys, Windows)* | **Yes**<br>*(Virtual sandbox / local)* | No | No | Limited<br>*(Docker browser)* | No | No | No |
| **Screen Perception Engine** | **Hybrid**<br>*(OS Accessibility + VLM)* | **Pure Vision**<br>*(Screenshots only)* | N/A | N/A | DOM / VNC | AST & Grep | Context / MCP | Text / Context |
| **Transparent Desktop HUD**<br>*(Click-through target boxes)* | **Yes**<br>*(Win32 / Tauri)* | No<br>*(In-app only)* | No | No | No | No | No | No |
| **Local Model Support**<br>*(Ollama, vLLM, llama.cpp)* | **Native & Offline** | No | No | No | Yes | Yes | Yes | Limited |
| **Frontier Cloud Models**<br>*(Anthropic, OpenAI, DeepSeek)* | **Any Provider**<br>*(LiteLLM unified)* | Anthropic Only | Anthropic Only | Google Gemini / DeepMind | Any Provider | Any Provider | Any Provider | Any Provider |
| **Automated Fallback Cascades**<br>*(Local $\to$ Cloud on failure)* | **Yes** | No | No | No | No | No | No | Partial |
| **Primary Interaction UI** | **Floating Dock + HUD + CLI** | Desktop Sidebar | Terminal CLI | Terminal CLI & IDE | Web Dashboard | Terminal CLI | Desktop App / CLI | Python SDK / CLI |
| **Safety Interruption** | **Global Hotkey (<kbd>Esc</kbd>)** | In-app Pause | <kbd>Ctrl+C</kbd> | <kbd>Ctrl+C</kbd> | Web Button | <kbd>Ctrl+C</kbd> | In-app Cancel | CLI interrupt |
| **Open Source License** | **Open Source (MIT)** | Proprietary | Proprietary | Open/Platform | Open Source (Apache 2.0) | Open Source (Apache 2.0) | Open Source (Apache 2.0) | Open Source |

---

## Why Emiliano?

1. **You Don't Have to Choose One Tool**: Instead of locking you into a single paradigm, Emiliano treats your existing tools (**Claude Code**, **Antigravity**, **OpenCode**, **Codex**, **Aider**) as specialized workers in a unified orchestrator.
2. **True Coworking with Non-Intrusive HUD**: Unlike web-only sandboxes or terminal-only agents, Emiliano works directly on your physical operating system. Its transparent HUD overlay draws visual crosshairs and bounding boxes on what it plans to click before acting.
3. **Local-First with Cloud Scale**: Start tasks completely offline using **Ollama** (`qwen2.5-coder`, `llama3.3`, `deepseek-r1`). If a task requires deep frontier reasoning, Emiliano smoothly cascades to Claude 3.7 Sonnet or GPT-4.5 with unified billing and key management.
4. **Instant Physical Safety**: Pressing <kbd>Esc</kbd> from any window immediately halts all mouse, keyboard, and sub-agent processes.

---

## Architecture Overview

```
emiliano/
├── apps/
│   └── desktop/        # Tauri + React Cowork UI (Floating Dock + HUD Overlay)
├── packages/
│   ├── engine/         # Python Meta-Harness Core + Cowork Perception Engine
│   └── protocol/       # Shared TypeScript & Python Schema Definitions
└── package.json        # Workspace configuration
```

## Features

- **Harness of Harnesses**: Orchestrates CLI-based agents (`claude-code`, `antigravity`, `opencode`, `codex`) via virtual pseudo-terminals (PTY) and standard MCP servers.
- **Direct Multi-Model Engine**: Direct execution loop supporting Ollama, vLLM, Anthropic, OpenAI, DeepSeek, with automated model fallback cascades.
- **Hybrid Screen Perception**: High-speed Windows UI Automation (UIA) tree inspection coupled with Set-of-Marks visual grounding for canvas/web views.
- **Transparent HUD Overlay**: Draws real-time visual bounding boxes and cursor trajectories over target elements before clicking.
- **Safety Kill-Switch**: Global hotkey (`Esc`) to instantly pause actions and release OS input controls.

## Development Setup

### 1. Engine (Python)

Navigate to the engine directory and create a virtual environment:

```bash
cd packages/engine
uv venv
```

Activate the environment based on your operating system and shell:

- **Linux / macOS**:
  ```bash
  source .venv/bin/activate
  ```
- **Windows (Git Bash / MINGW64)**:
  ```bash
  source .venv/Scripts/activate
  ```
  *(Note: Do not run `source .venv/bin/activate` in Git Bash on Windows; virtual environments on Windows create `.venv/Scripts/` rather than `.venv/bin/`.)*
- **Windows (PowerShell)**:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Windows (Command Prompt)**:
  ```cmd
  .venv\Scripts\activate.bat
  ```

Install the package in editable mode:

```bash
uv pip install -e .
```

Verify the installation and check system diagnostics:

```bash
emiliano --help
emiliano doctor
```

> **CLI Commands vs. Flags**: Subcommands in Emiliano are called as positional commands, or run bare `emiliano` to start coworking immediately:
> - `emiliano` or `emiliano chat`: Interactive terminal coworking session with floating `/` autocompletion, dynamic harness switching, real-time reasoning streaming, and persistent history
> - `emiliano doctor`: Full health check of models, credentials, and harnesses
> - `emiliano harnesses`: Status of external CLI agents (Claude Code, Codex, Antigravity, OpenCode)
> - `emiliano models`: Detected local Ollama models and remote API providers
> - `emiliano run "Your task"`: Direct execution with automatic intent-aware provider/harness routing
> - `emiliano server`: Background WebSocket daemon for Desktop Cowork UI

### 2. Desktop UI (Tauri)

The desktop app is a Tauri 2 shell around a React + TypeScript UI. It starts the Python engine itself (`emiliano-engine server`, bundled as a sidecar) and stops it on exit. Building it needs [Rust](https://rustup.rs) (on Windows also the Visual Studio C++ build tools); people who download the installer need neither.

```bash
yarn install
python scripts/build_engine_sidecar.py      # once, and after engine changes: builds the bundled engine
yarn workspace @emiliano/desktop tauri dev  # runs the desktop app with hot reload
```

To work on the UI against an engine you run yourself, start `emiliano server` and set `EMILIANO_EXTERNAL_ENGINE=1` before `tauri dev`. `yarn workspace @emiliano/desktop dev` serves the UI in a browser at `http://localhost:5173` without Rust.

## Quick Launch (Windows)

Double-click `Emiliano.bat` in the repository root to open the chat. On first run it creates `packages/engine/.venv` and installs the engine. To chat about a different project, drag that project's folder onto `Emiliano.bat`: the folder becomes the workspace.

## Releases

Pushing a `vX.Y.Z` tag runs `.github/workflows/release.yml`, which:

1. Builds a standalone `Emiliano.exe` with PyInstaller (`scripts/build_windows_release.py`) and smoke-tests it.
2. Packages `Emiliano-vX.Y.Z-windows-x64.zip` and a `version.json` manifest with SHA-256 checksums.
3. Builds the desktop app with the same engine bundled inside (`scripts/build_desktop_release.py`): `Emiliano-Desktop-vX.Y.Z-windows-x64-setup.exe` and `.msi`, added to `version.json`.
4. Uploads everything to Cloudflare R2 under `emiliano/vX.Y.Z/` and `emiliano/latest/` (`scripts/publish_release_to_r2.py`).
5. Deletes all but the newest **5** versioned releases (`scripts/prune_r2_releases.py`). The cap cannot be raised or disabled, and a failed prune fails the release. `latest/` is never deleted.
6. Creates a GitHub Release with the same files. The release fails unless the tag matches the version in `packages/engine/emiliano/__init__.py` and `apps/desktop/src-tauri/tauri.conf.json`; bump `pyproject.toml`, `apps/desktop/package.json` and `src-tauri/Cargo.toml` with them.

The workflow needs these repository secrets: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and optionally `R2_BUCKET_NAME` (default `plaatoos-downloads`) and `R2_CUSTOM_DOMAIN`.

To build locally without publishing:

```bash
packages/engine/.venv/Scripts/python.exe -m pip install pyinstaller  # or: uv pip install pyinstaller
packages/engine/.venv/Scripts/python.exe scripts/build_windows_release.py --version 0.1.0
```

To preview what the cap would delete: `python scripts/prune_r2_releases.py --dry-run` (needs the R2 variables).

---

## Documentation

- [Future Horizons & Architectural Roadmap](docs/future-horizons.md)
