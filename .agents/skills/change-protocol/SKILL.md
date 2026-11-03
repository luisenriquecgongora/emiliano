---
name: change-protocol
description: Change the wire contract between the Emiliano engine and the desktop app (message types, payload fields, HarnessType or TaskStatus values). Use when adding or renaming a WebSocket message, a payload field, or an enum value shared by Python and TypeScript.
---

# Change the engine <-> desktop protocol

The contract lives in `packages/protocol/` as two hand-mirrored files:

| File | Consumed by |
|---|---|
| `types.ts` | the desktop app (`apps/desktop/src/renderer/App.tsx` imports `@emiliano/protocol`) |
| `models.py` | nothing imports it yet: it documents the Python side. The engine builds these messages by hand in `packages/engine/emiliano/server/` |

Nothing checks that the two files agree, so a change is only done when **both files and the code that sends or reads the message** are updated.

## Steps

1. **Edit `types.ts` and `models.py` in the same commit.** Keep names identical:
   - enums: TS string union `'claude_code' | ...` <-> Python `class X(str, Enum)` with the same values;
   - fields: the same camelCase names on both sides (e.g. `modelConfig`), optional in TS (`?`) <-> `Optional[...] = None` in Python;
   - TS `XxxMessage { type, payload }` <-> Python `XxxPayload` for the payload part.
2. **Update the producers and consumers**:
   - engine side: `grep -rn "<message type or field>" packages/engine/emiliano/server`;
   - desktop side: `grep -rn "<message type or field>" apps/desktop/src`.
3. **Stay backward compatible when you can**: add optional fields rather than renaming; a renamed field breaks a desktop app talking to an older bundled engine.
4. **Engine changes ship inside the desktop app**: after changing engine code, rebuild the bundled engine with `python scripts/build_engine_sidecar.py` before testing the Tauri app.

## Done when

- `python scripts/verify.py` passes (the desktop typecheck catches TS consumers of a changed type);
- an engine test in `packages/engine/tests/test_server.py` covers any new or changed message.
