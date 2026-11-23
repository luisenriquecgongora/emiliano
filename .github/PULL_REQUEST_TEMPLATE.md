## What and why
<!-- What this PR changes and the reason for it. Link the issue if there is one. -->

## ⚡ Visual Delta (Fast Inspection)
<!--
Run `python scripts/visual-diff.py` to auto-generate this Mermaid diagram for staged changes,
or paste your custom flow delta using the docs/ARCHITECTURE.md palette:
-->

```mermaid
flowchart LR
    Caller["🟪 Caller / Trigger"] --> Component["🟦 Modified Component"]
    Component --> Output["🟩 Output / Result"]

    classDef ours fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef input fill:#ede9fe,stroke:#7c3aed,color:#3b0764
    classDef gate fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef done fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef risk fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class Caller input
    class Component ours
    class Output done
```

## Verification
- [ ] `python scripts/verify.py` passes (any skipped checks are listed below)
- [ ] Behavior changes come with a new or updated test
- [ ] Commits follow the conventions in `AGENTS.md`
- [ ] Visual delta diagram inspected (`python scripts/visual-diff.py --open`)

## Notes for review
<!-- Anything risky, follow-ups, or skipped checks. -->
