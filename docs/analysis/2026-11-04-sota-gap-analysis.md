# Gap Analysis vs. State of the Art

- **Date:** 2026-11-04
- **Status:** Final (point-in-time record; do not edit. Write a new dated analysis to supersede it.)
- **Scope:** `docs/future-horizons.md` roadmap and `packages/engine` as of commit `754530d`
- **Actions taken from it:** [Future Horizons §5](../future-horizons.md#5-next-steps-from-the-2026-11-04-gap-analysis)

---

## A. Status of the roadmap

| Item | Status |
| :--- | :--- |
| 1A Deep UI Automation | Not done. `cowork/perception.py` enumerates Win32 child windows only; Chrome, Electron and WinUI apps expose almost none, so only the top-level window comes back. |
| 1B DPI normalization | Partial. Per-monitor DPI awareness is set; screenshots cover the primary monitor only and coordinates are not normalized to the virtual desktop. |
| 1C `pyte` terminal grid | Not done (REPL foundation done). |
| 2A HWND pinning | Done (`cowork/pinning.py`). |
| 2B Shadow Mode preview | Done. |
| 3A Blackboard, 3B Skill Forge, Horizons 1–3 | Not started. |

## B. Missing steps

**P0 — prerequisites for the rest of the roadmap**
1. **Computer-use agent loop** (observe → plan → act → verify). Perception and actions are exposed as REST endpoints, but no model drives them; the README's Set-of-Marks/VLM grounding has no code yet. Frontier models now score ~85% on OSWorld-Verified, above the ~72% human baseline, so the harness (not the model) is the bottleneck.
2. **Hybrid perception, UFO²-style.** UIA first (`AutomationId`, `ControlType`, Invoke/Value patterns), a vision parser (e.g. OmniParser) for custom-drawn controls, and app-native APIs where available. Supersedes 1A.
3. **Agent Client Protocol (ACP) adapters** for harnesses instead of scraping stdout. Claude Code, Gemini CLI and Codex (via `codex-acp`) speak ACP, giving structured tool calls, permission requests, sessions and diffs. `pyte` (1C) becomes the fallback for non-ACP agents.
4. **Harness approvals and safety.** Codex runs with `--dangerously-bypass-approvals-and-sandbox` and Antigravity with `--dangerously-skip-permissions` (`harnesses/base.py`). Route ACP permission requests to the dock. Add prompt-injection defenses for screen/web content, confirmation before irreversible actions, secret redaction in screenshots, and a replayable action audit log.

**P1 — measurability and integration**

5. **Evaluation suite**: golden tasks plus a Windows Agent Arena / OSWorld subset, and routing evals. Required to measure Skill Forge and self-healing.
6. **Learned routing.** `requires_agent_harness` in `core/dispatcher.py` is keyword matching; replace with a small-model classifier and log decisions for evals.
7. **MCP**: expose cowork actions as an MCP server (lets any harness drive the desktop; a cheap first Blackboard) and consume MCP servers in direct mode.
8. **Observability and cost**: OpenTelemetry GenAI traces, per-task token/cost budgets, prompt caching for cloud models.
9. **Parallel isolation**: one git worktree per harness, then compare or merge results (best-of-n).

**P2 — refinements to existing items**
- **Skill Forge**: record UIA selectors and preconditions, not coordinates; store as `SKILL.md` skills.
- **Self-healing**: use UIA events (window opened, structure changed) as a cheap check before visual diffs.
- **Ghost Worker**: intermediate step — UIA Invoke/Value patterns act without moving the cursor; then Windows Sandbox or Hyper-V.
- **Blackboard**: define schema and conflict rules; evaluate A2A or MCP resources before a custom store.
- **README accuracy**: update model names (Claude 3.7, GPT-4.5) and mark unbuilt features (UIA, Set-of-Marks, MCP) as planned.

## C. Suggested order
ACP adapters + dock approvals (3, 4) → UIA perception (2) → computer-use loop (1) → evals (5) → MCP server (7) → the rest.

## Caveats
Leaderboard figures come from aggregator sites that disagree with each other; treat them as approximate. ACP support status for Codex was still settling at the time of writing.

## References
- UFO²: The Desktop AgentOS — https://arxiv.org/abs/2504.14603
- Agent Client Protocol overview — https://www.morphllm.com/agent-client-protocol
- ACP and Codex CLI — https://codex.danielvaughan.com/2026/06/10/agent-client-protocol-microsoft-intelligent-terminal-codex-cli-multi-agent-ide-ecosystem/
- OSWorld-Verified results — https://www.benchlm.ai/benchmarks/osworld-verified
