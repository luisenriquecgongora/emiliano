# Engineering Standards & Observability Contract

### 1. Pre-Change Invariant Manifest
Before executing code modifications touching more than one file, output a compact change manifest table:

| Target File / Module | Nature of Change | Breaking / Invariant Impact |
| :--- | :--- | :--- |
| `path/to/file` | `[refactor / feat / fix / rename]` | `None / Exposes new method / Renames prop` |

Do not output narrative summaries, conversational setups, or ad-hoc diagrams.

### 2. Diff Noise & Spurious Edit Invariants
- **No Unsolicited Formatting:** Do NOT reformat, re-indent, or adjust comments on lines unrelated to your assigned task. Leave untouched code exactly as it is.
- **Import Hygiene:** Do not randomly shuffle or re-order existing import statements unless adding or removing an active dependency.
- **Isolate Mass Renames:** If a task requires renaming an identifier across multiple files, isolate that rename into a dedicated `refactor(<scope>): rename X to Y` commit with ZERO other logic changes.

### 3. Conventional Commit Standards
All commits must follow:
`<type>(<scope>): <short imperative subject under 50 chars>`

- **Allowed Types:** `feat`, `fix`, `refactor`, `perf`, `chore`, `test`, `docs`, `build`, `ci` (add `model`, `data`, `eval`, `exp` for ML pipelines).
- **Allowed Scopes:** [`desktop`, `engine`, `protocol`, `cli`, `core`, `cowork`, `direct`, `harness`, `server`, `config`, `deps`, `hooks`, `ci`, `docs`]
- **Rule:** Never mention AI, LLMs, or prompt tools in commit messages.

### 4. Commit Granularity & Invariants
- **Atomic Commits:** Do not bundle refactorings, feature code, and config tweaks into a single commit.
- **Commit Sequence:**
  1. `refactor(<scope>): ...` (Structural prep or renames only)
  2. `feat(<scope>): ...` or `fix(<scope>): ...` (Logic changes)
  3. `test(<scope>): ...` (Specs/tests)
- **Blast-Radius Cap:** A single commit must not exceed 5 staged files (excluding lockfiles/documentation).
- **Bisect Safety:** Every individual commit must compile and pass tests.

### 5. Definition of Done
- Run `python scripts/verify.py` (or `yarn verify`) before reporting a task complete. It runs exactly what CI runs: ruff, engine tests, release-retention tests, CLI sanity, desktop typecheck, and a secret scan when `gitleaks` is installed.
- Narrow it while iterating: `--only python`, `--only desktop`, `--only secrets`.
- In a git worktree there is no virtualenv: set `EMILIANO_PYTHON` to the main checkout's `packages/engine/.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`.
- A task that changes behavior adds or updates a test in `packages/engine/tests/`.

### 6. Repository Map
| Path | What lives there |
| :--- | :--- |
| `packages/engine/emiliano/cli.py` | Click CLI: `chat`, `run`, `server`, `doctor`, `harnesses`, `models` |
| `packages/engine/emiliano/core/dispatcher.py` | Routes a goal to a direct model or an agent harness (`RoutingPolicy`: auto/local/harness/api) |
| `packages/engine/emiliano/core/registry.py` | Discovers providers and harnesses, their credentials and models |
| `packages/engine/emiliano/core/config.py` | `EmilianoConfig`; loaded from `./emiliano.yaml`, then `~/.emiliano/config.yaml` |
| `packages/engine/emiliano/core/context*` | Context-window truncation, summarization, persistent context, metrics |
| `packages/engine/emiliano/harnesses/base.py` | `BaseHarness` + Claude Code, Codex, Antigravity, OpenCode adapters |
| `packages/engine/emiliano/direct/` | LiteLLM client, credential lookup, Ollama management |
| `packages/engine/emiliano/server/` | FastAPI daemon: `/health`, `/api/models`, WebSocket `/ws`; chat history REST at `/api/chats` and WebSocket `/api/chat`; origin allowlist in `security.py` |
| `packages/engine/emiliano/history/` | SQLite chat history store and API |
| `packages/engine/emiliano/cowork/` | Desktop perception and input actions |
| `packages/protocol/` | Wire contract: `types.ts` and `models.py` are hand-mirrored; change both together |
| `apps/desktop/` | Tauri 2 + React 19 UI; spawns the engine sidecar on port 8765 |
| `scripts/` | Release build, R2 publish/prune, `verify.py` |

### 7. Commands
- Engine setup: `cd packages/engine && uv venv && uv pip install -e ".[dev]"`
- Engine daemon: `emiliano server` (port 8765)
- Desktop UI in a browser, no Rust: `yarn workspace @emiliano/desktop dev` (http://localhost:5173)
- Desktop app against your own engine: start `emiliano server`, set `EMILIANO_EXTERNAL_ENGINE=1`, then `yarn workspace @emiliano/desktop tauri dev`
- Rebuild the bundled engine after engine changes: `python scripts/build_engine_sidecar.py`

### 8. Gotchas
- The engine port `8765` is hard-coded in six places: `renderer/engine.ts`, `renderer/chats.ts`, `src-tauri/src/main.rs`, the CSP in `src-tauri/tauri.conf.json`, the `--port` default in `cli.py`, and `ServerConfig.port` in `core/config.py`. Change all of them together (`grep -rn 8765`).
- New browser origins for the WebSocket must be added to `DEFAULT_ALLOWED_ORIGINS` in `server/security.py`, or the connection is rejected.
- `packages/engine/README.md` must exist: Hatchling reads it for the editable install.
- Ruff rules live in the root `ruff.toml`; do not add per-file configs.

### 9. Never
- Never read, print or commit `.env` files, API keys, or files under `credentials/`.
- Never force-push, rewrite published history, or commit directly to `main` or `prod`.
- Never commit `dist/`, `build/`, `src-tauri/target/` or `src-tauri/binaries/`.
