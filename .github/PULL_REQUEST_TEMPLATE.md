## Description
<!-- Provide a brief description of what this PR does and the rationale behind the changes. -->

## Type of Change
- [ ] 🐛 Bug fix (non-breaking change fixing an issue)
- [ ] ✨ New feature (non-breaking change adding functionality or a new harness adapter)
- [ ] 💥 Breaking change (fix or feature that alters existing behavior or protocol)
- [ ] 📝 Documentation update
- [ ] 🛡️ Security / Safety guardrail enhancement

## Subsystems Affected
- [ ] `packages/engine` (Python Meta-Harness & Direct Execution Engine)
- [ ] `packages/protocol` (Shared TypeScript/Python schemas)
- [ ] `apps/desktop` (Tauri Cowork UI & HUD Overlay)
- [ ] CI/CD or Repository tooling

## Diagram
<!-- If this changes a structure or a flow: a small colored Mermaid diagram of the new shape, and the
     updated docs/ARCHITECTURE.md. Delete this section otherwise. -->

## Verification & Testing
<!-- Describe how you verified your changes (e.g. CLI run, desktop app smoke test, unit tests). -->
- [ ] Tested locally with `python -m emiliano.cli harnesses`
- [ ] Emergency stop (<kbd>Esc</kbd>) remains functional
- [ ] Code formatted and typechecked
- [ ] `python scripts/verify.py` passes (any skipped checks are listed below)

## Checklist
- [ ] I have read the [CONTRIBUTING.md](CONTRIBUTING.md) guide.
- [ ] My code adheres to the project style guidelines.
- [ ] I have updated documentation where appropriate.
