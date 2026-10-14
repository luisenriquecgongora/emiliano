# Emiliano Engine

> *The Python Meta-Harness and Direct Execution Engine for Emiliano.*

The Engine (`packages/engine`) serves as Emiliano's intelligent brain and execution supervisor. It bridges two distinct execution mechanisms:
1. **Direct Model Providers**: Direct LLM prompting via local runtimes (**Ollama**, vLLM) and remote frontier APIs (**Anthropic Claude**, **OpenAI GPT**, **DeepSeek**, **Google Gemini**).
2. **External Agent Harnesses**: Delegation to installed autonomous CLI agents (**Claude Code**, **Codex**, **Antigravity (AGY)**, **OpenCode**).

---

## Development Setup

### 1. Prerequisites
- **Python**: 3.10, 3.11, or 3.12
- **uv**: Fast Python package installer and resolver (`curl -LsSf https://astral.sh/uv/install.sh` or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`)

### 2. Create the Virtual Environment
From `packages/engine`:

```bash
cd packages/engine
uv venv
```

### 3. Activate the Environment

Virtual environment activation paths differ between Unix/Linux and Windows:

- **Linux / macOS**:
  ```bash
  source .venv/bin/activate
  ```

- **Windows (Git Bash / MINGW64)**:
  ```bash
  source .venv/Scripts/activate
  ```
  *(Note: Do not run `source .venv/bin/activate` in Git Bash on Windows; Windows virtual environments create `.venv/Scripts` rather than `.venv/bin`.)*

- **Windows (PowerShell)**:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```

- **Windows (Command Prompt)**:
  ```cmd
  .venv\Scripts\activate.bat
  ```

### 4. Install the Package in Editable Mode

```bash
uv pip install -e .
```

> **Note on `README.md`**: `pyproject.toml` declares `readme = "README.md"`. This file (`packages/engine/README.md`) must exist for Hatchling to build and install the package in editable mode.

---

## Command-Line Interface (`emiliano`)

Once installed and activated, the `emiliano` command is registered directly on your terminal PATH.

```bash
emiliano --help
```

*(Alternatively, you can run `python -m emiliano.cli --help`)*

> **Important**: Emiliano commands are **subcommands**, not flags:
> - Use `emiliano harnesses` (not `emiliano --harnesses`)
> - Use `emiliano models` (not `emiliano --models`)
> - Use `emiliano doctor` (not `emiliano --doctor`)

---

## Available Commands

### 1. `emiliano doctor`
Runs a comprehensive diagnostic check across all direct model providers, API credentials, and external agent harnesses.

```bash
emiliano doctor
```

Reports:
- Platform, Python runtime, and configured execution policy.
- Local Ollama installation, endpoint readiness, and auto-selected model.
- Configured remote API credentials (redacted for security).
- Detected external agent harnesses, executable paths, versions, and authentication states.

### 2. `emiliano harnesses`
Discovers and inspects external agent harnesses available on your system.

```bash
emiliano harnesses
```

Checks:
- **Claude Code** (`claude`): Verified via `--version` and account authentication (`~/.claude.json` or `ANTHROPIC_API_KEY`).
- **Codex** (`codex`): Verified via `--version` and auth tokens (`~/.codex/auth.json` or `OPENAI_API_KEY`).
- **Antigravity** (`agy`): Verified via `--version` and settings (`~/.gemini/antigravity-cli/settings.json`).
- **OpenCode** (`opencode`): Verified via `-v` and credential configuration (`~/.local/share/opencode/auth.json`).

### 3. `emiliano models`
Inspects local Ollama models and remote API providers.

```bash
emiliano models
```

- Connects to the local Ollama API (default: `http://localhost:11434/api/tags`).
- Automatically lists installed models (e.g. `qwen3.5:2b`).
- Indicates which model was automatically selected for coding tasks.
- Displays remote API providers with masked credential statuses.

### 4. `emiliano run`
Executes an autonomous task directly from your terminal using intelligent routing and automated fallback.

```bash
emiliano run "Explain what this repository does"
```

#### Routing Options:
- `--policy, -p`: Execution routing policy:
  - `auto` *(default)*: Prefers ready local models (Ollama), then delegates to ready agent harnesses, then remote APIs.
  - `local`: Enforces local-only execution via Ollama.
  - `harness`: Prioritizes delegation to external agent harnesses (Claude Code, Codex, Antigravity, OpenCode).
  - `api`: Uses direct remote API models (Anthropic, OpenAI, DeepSeek, Gemini).
- `--harness`: Explicitly override the agent harness (e.g. `--harness codex`, `--harness claude`).
- `--provider`: Explicitly override the direct provider (e.g. `--provider ollama`, `--provider anthropic`).
- `--model, -m`: Explicitly override the model name (e.g. `-m qwen3.5:2b`, `-m claude-3-7-sonnet-20250219`).
- `--timeout`: Set task timeout in seconds (default: `180.0`).

#### Examples:
```bash
# Auto routing (uses local Ollama model if ready, or available harness)
emiliano run "Analyze the project structure"

# Force delegation to external Codex harness
emiliano run "Refactor perception.py" --policy harness

# Force local Ollama execution with specific model
emiliano run "Generate test cases" --policy local -m qwen3.5:2b
```

### 5. `emiliano server`
Starts the background WebSocket IPC daemon bridging the Python engine to the Electron desktop Cowork UI.

```bash
emiliano server --port 8765 --host 127.0.0.1
```

Includes a single-instance guard to prevent duplicate daemon processes from running concurrently.

---

## Configuration & Credentials

Emiliano loads configuration from `emiliano.yaml` (in current working directory) or `~/.emiliano/config.yaml`.

Example configuration (`emiliano.yaml`):

```yaml
execution_policy: "auto"    # "auto" | "local" | "harness" | "api"

models:
  default_provider: "ollama"
  ollama_base_url: "http://localhost:11434"
  auto_start_ollama: false
  ollama_timeout: 120.0

harnesses:
  claude_code_cmd: "claude"
  codex_cmd: "codex"
  antigravity_cmd: "agy"
  opencode_cmd: "opencode"

server:
  host: "127.0.0.1"
  port: 8765
```

### Environment Variables
- `ANTHROPIC_API_KEY`: API key for Anthropic Claude models.
- `OPENAI_API_KEY`: API key for OpenAI GPT models.
- `DEEPSEEK_API_KEY`: API key for DeepSeek models.
- `GEMINI_API_KEY`: API key for Google Gemini models.

> **Security**: Emiliano never logs, prints, or exposes credentials. In auto-routing mode, unconfigured providers are skipped automatically instead of causing runtime failures.

---

## Running Tests

From `packages/engine`:

```bash
# Using python unittest
python -m unittest discover tests

# Or with uv run
uv run python -m unittest discover tests
```
