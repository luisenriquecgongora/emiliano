# Emiliano

> *An autonomous desktop coworker and meta-harness for intelligent multi-agent orchestration.*

`emiliano` combines two complementary systems into a unified platform:
1. **The Meta-Harness & Direct Execution Engine (`packages/engine`)**: A supervisor that controls and delegates work to external agent harnesses (Claude Code, Antigravity, OpenCode, Codex, MCP) or directly executes tasks via local models (Ollama, vLLM) and remote frontier APIs (Claude 3.7, GPT-4.5, DeepSeek, Gemini).
2. **The Desktop Cowork UI (`apps/desktop`)**: An Electron-based desktop coworker inspired by Anthropic's Claude Cowork, featuring a collapsible floating dock, non-blocking click-through transparent HUD overlay, and hybrid screen perception (Windows UI Automation + Multimodal Vision).

---

## Comparison Matrix: Emiliano vs. Other Harnesses

| Capability / Dimension | **Emiliano** | **Claude Cowork** | **Claude Code** | **Antigravity (AGY)** | **OpenHands** | **Aider** | **Goose** | **Raven** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Harness Architecture** | **Meta-Harness + Direct Engine** | Single Agent Coworker | Single CLI Agent | Single CLI & IDE Agent | Sandbox Web Agent | Git Pair Programmer | Extensible Desktop Agent | Meta-Harness (DAG RSI) |
| **Multi-Harness Orchestration**<br>*(Controls external CLI/API agents)* | **Yes**<br>*(Claude, AGY, OpenCode, Codex)* | No | No | No | No | No | No | **Yes**<br>*(Internal sub-agents)* |
| **OS Screen & GUI Manipulation**<br>*(Controls arbitrary desktop apps)* | **Yes**<br>*(Mouse, Keys, Windows)* | **Yes**<br>*(Virtual sandbox / local)* | No | No | Limited<br>*(Docker browser)* | No | No | No |
| **Screen Perception Engine** | **Hybrid**<br>*(OS Accessibility + VLM)* | **Pure Vision**<br>*(Screenshots only)* | N/A | N/A | DOM / VNC | AST & Grep | Context / MCP | Text / Context |
| **Transparent Desktop HUD**<br>*(Click-through target boxes)* | **Yes**<br>*(Win32 / Electron)* | No<br>*(In-app only)* | No | No | No | No | No | No |
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
│   └── desktop/        # Electron + React Cowork UI (Floating Dock + HUD Overlay)
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

> **CLI Commands vs. Flags**: Subcommands in Emiliano are called as positional commands, not flags:
> - `emiliano doctor` (not `--doctor`): Full health check of models, credentials, and harnesses
> - `emiliano harnesses` (not `--harnesses`): Status of external CLI agents (Claude Code, Codex, Antigravity, OpenCode)
> - `emiliano models` (not `--models`): Detected local Ollama models and remote API providers
> - `emiliano run "Your task"`: Direct execution with automatic provider/harness routing
> - `emiliano server`: Background WebSocket daemon for Desktop Cowork UI

### 2. Desktop UI (Electron)
```bash
yarn install
yarn workspace @emiliano/desktop dev
```

---

## Documentation

- [Future Horizons & Architectural Roadmap](docs/future-horizons.md)
