# Contributing to Emiliano

Thank you for your interest in contributing to **Emiliano**! We welcome contributions from developers, researchers, and designers across the open-source community.

---

## 1. Development Setup

Emiliano is organized as a monorepo containing:
- `packages/engine`: Python 3.10+ (Core Meta-Harness & Cowork Engine)
- `packages/protocol`: Shared TypeScript & Python contracts
- `apps/desktop`: Electron + React 19 + TypeScript (Desktop Cowork UI)

### Prerequisites
- Python 3.10+ (Recommended: [uv](https://github.com/astral-sh/uv))
- Node.js 20+
- Yarn 1.22+

### Quick Setup

```bash
# Clone the repository
git clone https://github.com/<your-org>/emiliano.git
cd emiliano

# Install Node & Desktop workspace dependencies
yarn install

# Setup Python Engine with UV
cd packages/engine
uv venv
# Windows:
.venv\Scripts\activate
# Unix/macOS:
source .venv/bin/activate

uv pip install -e ".[dev]"
```

---

## 2. Adding a New Harness Adapter

To add support for a new agent harness (e.g., adding a new CLI agent):

1. Open `packages/engine/emiliano/harnesses/base.py`.
2. Subclass `BaseHarness`:
   ```python
   class MyNewHarness(BaseHarness):
       def __init__(self, command: str = "mytool"):
           super().__init__(name="my_new_tool", command=command)

       def start_task(self, prompt: str, cwd: Optional[str] = None, on_chunk: Optional[Callable[[str], None]] = None) -> bool:
           cmd = f'{self.command} --goal "{prompt}"'
           self.session = SubprocessPTYSession(command=cmd, cwd=cwd, on_output=on_chunk)
           return self.session.start()
   ```
3. Register the harness in `packages/protocol/types.ts` and `models.py`.
4. Add the harness detection path to `core/config.py` and `cli.py harnesses`.

---

## 3. Pull Request Guidelines

1. **Branch Naming**: Use descriptive branch names:
   - `feat/add-goose-harness`
   - `fix/uia-coordinate-scaling`
   - `docs/clarify-security-policy`
2. **Formatting & Linting**:
   - Python: Run `ruff check .` and `black .` inside `packages/engine`.
   - TypeScript: Run `yarn format` and `yarn lint` at root.
3. **Commit Messages**: Write clear, imperative commit messages (e.g. `feat: add per-monitor DPI scaling to screen perceiver`).
4. **Safety & Tests**: Ensure all automated tests pass before submitting your PR.

---

## 4. Commit Standards & Git Hooks

After cloning, activate the local git config and commit hooks once:

```bash
./scripts/setup-hooks.sh
```

This enforces conventional commit messages (`<type>(<scope>): <subject>`), blocks trailing whitespace, caps commits at 5 staged files (excluding lockfiles and docs), and rejects commits that mix build configuration with application source. See `AGENTS.md` for the full contract and allowed scopes. Existing hooks are preserved as `<hook>.local` and still run.
