# Emiliano

> *An autonomous desktop coworker and meta-harness for intelligent multi-agent orchestration.*

`emiliano` combines two complementary systems into a unified platform:
1. **The Meta-Harness & Direct Execution Engine (`packages/engine`)**: A supervisor that delegates work to external agent harnesses (Claude Code, Antigravity, OpenCode, Codex) or answers directly with local models (Ollama) and remote APIs (Claude, GPT, DeepSeek, Gemini through LiteLLM). Local models come first: it works offline.
2. **The Desktop Cowork UI (`apps/desktop`)**: A Tauri-based desktop coworker (the Python engine ships inside it) inspired by Anthropic's Claude Cowork, featuring a collapsible floating dock, non-blocking click-through transparent HUD overlay, and screen perception through Windows UI Automation (a vision fallback is planned).

## Try It Now (Windows)

Clone the repository, then double-click one of these launchers in its root:

| Launcher | Opens | Needs |
| :--- | :--- | :--- |
| [**`Emiliano.bat`**](Emiliano.bat) | Terminal chat | Python 3.10+ |
| [**`Emiliano-Desktop.bat`**](Emiliano-Desktop.bat) | Desktop app: floating dock + HUD overlay, with Approve/Deny prompts when an agent asks permission | Python 3.10+, Node with yarn, [Rust](https://rustup.rs) |

Both run the code in your checkout, so they are the quickest way to test changes. Drag a project folder onto either one to use it as the workspace. See [Quick Launch](#quick-launch-windows) for details.

---

## Comparison Matrix: Emiliano vs. Other Harnesses

As of November 2026. Rows describe what Emiliano does today; see [Planned](#planned-not-built-yet) for what it does not do yet.

| Capability / Dimension | **Emiliano** | **Claude Cowork** | **Claude Code** | **Antigravity (AGY)** | **OpenHands** | **Aider** | **Goose** | **Raven** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Harness Architecture** | **Meta-Harness + Direct Engine** | Single Agent Coworker | CLI Agent (+ subagents) | Agent Manager, CLI & IDE (parallel subagents) | Sandbox Web Agent | Git Pair Programmer | Extensible Desktop Agent | Meta-Harness (DAG RSI) |
| **Multi-Harness Orchestration**<br>*(Controls external CLI/API agents)* | **Yes**<br>*(Claude, AGY, OpenCode, Codex)* | No | No | No | No | No | No | **Yes**<br>*(Internal sub-agents)* |
| **OS Screen & GUI Manipulation**<br>*(Controls arbitrary desktop apps)* | **Yes**<br>*(Mouse, Keys, Windows)* | **Yes**<br>*(Virtual sandbox / local)* | No | No | Limited<br>*(Docker browser)* | No | No | No |
| **Screen Perception Engine** | **OS Accessibility**<br>*(UI Automation; vision fallback planned)* | **Pure Vision**<br>*(Screenshots only)* | N/A | N/A | DOM / VNC | AST & Grep | Context / MCP | Text / Context |
| **Transparent Desktop HUD**<br>*(Click-through target boxes)* | **Yes**<br>*(Win32 / Tauri)* | No<br>*(In-app only)* | No | No | No | No | No | No |
| **Local Model Support**<br>*(Ollama, vLLM, llama.cpp)* | **Native & Offline** | No | No | No | Yes | Yes | Yes | Limited |
| **Frontier Cloud Models**<br>*(Anthropic, OpenAI, DeepSeek)* | **Any Provider**<br>*(LiteLLM unified)* | Anthropic Only | Anthropic Only | Gemini and Claude | Any Provider | Any Provider | Any Provider | Any Provider |
| **Automated Fallback Cascades**<br>*(Local $\to$ Cloud on failure)* | **Yes** | No | No | No | No | No | No | Partial |
| **Primary Interaction UI** | **Floating Dock + HUD + CLI** | Desktop Sidebar | Terminal CLI | Terminal CLI & IDE | Web Dashboard | Terminal CLI | Desktop App / CLI | Python SDK / CLI |
| **Safety Interruption** | **Global Hotkey (<kbd>Esc</kbd>)** | In-app Pause | <kbd>Ctrl+C</kbd> | <kbd>Ctrl+C</kbd> | Web Button | <kbd>Ctrl+C</kbd> | In-app Cancel | CLI interrupt |
| **License** | **PolyForm Shield 1.0.0** | Proprietary | Proprietary | Open/Platform | Open Source (Apache 2.0) | Open Source (Apache 2.0) | Open Source (Apache 2.0) | Open Source |

---

## Why Emiliano?

1. **You Don't Have to Choose One Tool**: Instead of locking you into a single paradigm, Emiliano treats your existing tools (**Claude Code**, **Antigravity**, **OpenCode**, **Codex**, **Aider**) as specialized workers in a unified orchestrator.
2. **True Coworking with Non-Intrusive HUD**: Unlike web-only sandboxes or terminal-only agents, Emiliano works directly on your physical operating system. Its transparent HUD overlay draws visual crosshairs and bounding boxes on what it plans to click before acting.
3. **Local-First with Cloud Scale**: Run completely offline with any **Ollama** model (`qwen3.5`, `qwen2.5-coder`, `llama3.3`, ...). When a local model fails, Emiliano falls back to the cloud providers you have keys for (Claude, GPT, DeepSeek, Gemini), with keys kept out of agent processes. See [Local models](#local-models).
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

- **Harness of Harnesses**: Runs coding agents (`claude-code`, `codex`, `opencode`, `antigravity`) over the Agent Client Protocol (ACP) where an adapter is installed, with each permission request shown in the dock for you to approve; otherwise as a plain CLI process.
- **Direct Multi-Model Engine**: Answers with Ollama, Anthropic, OpenAI, DeepSeek or Gemini models, with automatic fallback between them.
- **Screen Perception**: Reads other apps' controls through Windows UI Automation (UIA), including browsers and Electron apps such as VS Code; falls back to Win32 child windows.
- **Transparent HUD Overlay**: Draws bounding boxes over target elements before clicking.
- **Safety Kill-Switch**: Global hotkey (`Esc`) to instantly pause actions and release OS input controls.
- **Task Traces**: Every task records its route, fallbacks, time to first output, duration and tokens/s on your machine (`emiliano traces`).

### Planned (not built yet)

Vision fallback (Set-of-Marks) for custom-drawn controls, acting through UIA without moving the cursor, an MCP server for cowork actions, and parallel agents in git worktrees. Order and status: [Future Horizons](docs/future-horizons.md).

## Local models

Emiliano is built to work well with models on your own machine through [Ollama](https://ollama.com):

```bash
ollama pull qwen3.5:2b        # small and fast; pick a bigger model if you have the memory
emiliano run "Explain what a context window is" --provider ollama
emiliano traces               # time to first output and tokens/s for each task
```

- **Context window.** Emiliano asks Ollama for `models.ollama_num_ctx` tokens (default 8192) and fits conversations into that same size. Ollama's own default is small and silently drops the start of longer prompts. A larger window needs more memory: try 16384–32768 with 16 GB or more of VRAM.
- **Offline.** No internet is needed: token counting uses an encoding bundled with the engine, and traces stay in `~/.emiliano/traces.db` (set `traces: false` in the config to turn them off).
- **Compare models.** `emiliano eval local-basics --target ollama:<model>` scores a model on short, automatically checked questions (format following, arithmetic, JSON, reading code, Spanish, a long prompt) and reports time to first output and tokens/s. Run it for each model you are considering.

## Evals

`emiliano eval` runs fixed tasks with automatic checks and saves a JSON report to `~/.emiliano/evals/`:

```bash
emiliano eval --list                              # built-in suites
emiliano eval routing                             # is each goal sent to a model or a coding agent? (no model calls)
emiliano eval local-basics --target ollama        # a local model's answers and speed
emiliano eval coding --target claude_code         # can an agent fix small projects? (codex, opencode, ...)
```

Add a task by editing a YAML file in `packages/engine/emiliano/evals/suites/`. How it works: [Architecture](docs/ARCHITECTURE.md#measuring-traces-and-evals).

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
> - `emiliano traces`: Recent tasks with their route, time to first output, duration and tokens/s
> - `emiliano eval`: Run eval suites against a model or coding agent (see [Evals](#evals))
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

**Chat history.** Chats are saved on your machine in `~/.emiliano/history.db` (set `EMILIANO_HISTORY_DB` to use another file). In the dock, the clock button lists them, newest first: click one to reopen it, or use the trash icon (or "Clear all history") to delete. Deleted chats cannot be restored. The engine serves them at `/api/chats` and streams replies over `/api/chat`; both only answer the desktop app (requests must address `127.0.0.1`/`localhost` and come from the app's origin).

**Modes.** The dropdown under the message box picks who answers: *Auto* (Emiliano decides), *Local model* (Ollama), or a specific agent (Claude Code, Codex, Antigravity, OpenCode). Plain conversation is answered directly, with the model's step-by-step reasoning turned off for speed; tasks keep reasoning and also see the project's `EMILIANO.md`/`CLAUDE.md`.

## Quick Launch (Windows)

- **[`Emiliano.bat`](Emiliano.bat)**: double-click to open the terminal chat. On first run it creates `packages/engine/.venv` and installs the engine. To chat about a different project, drag that project's folder onto `Emiliano.bat`: the folder becomes the workspace.
- **[`Emiliano-Desktop.bat`](Emiliano-Desktop.bat)**: double-click to open the desktop app (dock + HUD overlay) on the code in this checkout. It starts the engine in its own window (close that window to stop the engine), then runs `tauri dev`. On first run it also installs the desktop dependencies and builds the bundled engine binary, and the first Rust build takes a few minutes. Close the installed Emiliano app first: both use port 8765. Drag a folder onto it to use that folder as the workspace.

Agent permission requests appear in the dock only. The terminal chat approves them automatically, as before.

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
