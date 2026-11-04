# 0001. Use the Agent Client Protocol for harness integration

- **Status:** Proposed
- **Date:** 2026-11-04
- **Source:** [2026-11-04 gap analysis](../analysis/2026-11-04-sota-gap-analysis.md), P0 items 3 and 4

## Context

`harnesses/base.py` runs each external agent (Claude Code, Codex, Antigravity, OpenCode) as a subprocess in non-interactive mode and streams its stdout as plain text. This has three consequences:

- Emiliano cannot see tool calls, file edits or plan steps as structured events; the dock can only show text.
- The agents cannot ask the user for permission, so adapters disable approvals: Codex runs with `--dangerously-bypass-approvals-and-sandbox` and Antigravity with `--dangerously-skip-permissions`.
- Each adapter needs its own prompt-passing and output quirks (stdin, `-f` temp files, `stream-json`), and sessions cannot be resumed.

The Agent Client Protocol (ACP) is a JSON-RPC protocol over stdio between a client (editor, terminal, orchestrator) and a coding agent. By mid-2026 Claude Code (Claude Agent adapter), Gemini CLI and Codex (`codex-acp`) are reachable through it, and Zed and Windows Terminal act as clients.

## Decision

Emiliano becomes an ACP client. Each harness adapter first tries to start the agent's ACP server; if the agent has no ACP support, the adapter falls back to the current subprocess mode.

- ACP session updates (messages, tool calls, diffs, plans) map to protocol events sent to the desktop over the existing WebSocket.
- ACP permission requests are shown in the dock and answered by the user, or by a per-workspace policy (allow-list of tool kinds).
- The `--dangerously-*` flags are no longer passed by default on the ACP path. On the fallback path they stay behind an explicit config opt-in.

## Alternatives considered

| Option | Why not |
| :--- | :--- |
| Keep stdout scraping, add `pyte` screen emulation | Better text, still no structured events or permission flow; each agent's output format can change without notice. |
| Per-vendor SDKs (Claude Agent SDK, Codex SDK) | Structured, but one integration per vendor in different languages; does not cover OpenCode, Gemini CLI or future agents. |
| MCP only | MCP gives agents tools; it does not let a client drive an agent's session or receive its permission requests. Complementary, not a replacement. |

## Consequences

- **Positive:** structured events in the dock; real human-in-the-loop approvals; session resume; one integration path for any ACP agent.
- **Negative:** new dependency on ACP spec versions; adapters must handle agents with partial or community-maintained ACP support; `packages/protocol` (`types.ts` and `models.py`) gains new event types and must be changed in both files together.
- **Follow-ups:** add an ACP client module under `packages/engine/emiliano/harnesses/`; update the `add-harness-adapter` skill; tests with a fake ACP agent in `packages/engine/tests/`.
