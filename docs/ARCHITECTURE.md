# Architecture

The map of Emiliano: what its parts are, how a request becomes work done by a model or a coding agent, and
where to change what. Keep it current: a change that adds, removes or rewires a part updates the diagram in
the same pull request (`AGENTS.md`, section 11).

## Color palette

| Color | Meaning |
| :--- | :--- |
| 🟦 Blue | Our code: engine, desktop app, protocol |
| 🟪 Purple | Inputs: the user's request, configuration |
| 🟨 Yellow | Decisions and safety checks |
| 🟩 Green | Outputs and stored results |
| ⬜ Grey | External programs and services we do not own |
| 🟥 Red | Risky: API keys, control of the mouse and keyboard |

## The big picture

Emiliano is a desktop assistant that sends each request to the best place to run it: a local model, a cloud
model, or a coding agent (Claude Code, Codex, OpenCode, Antigravity). It can also see and operate other windows
("Cowork").

```mermaid
flowchart LR
    user["👤 User<br/>types a request"] --> desktop
    subgraph desktop["Desktop app · apps/desktop · Tauri + React"]
        direction TB
        ui["Chats, Dock, HUD overlay<br/>src/renderer"]
    end
    desktop -.->|starts the engine as a sidecar process| engine
    desktop <-->|"WebSockets on 127.0.0.1:8765<br/>/api/chat: chats, permission prompts<br/>/ws: tasks, typed by packages/protocol"| server
    subgraph engine["Engine · packages/engine · Python"]
        direction TB
        server["Server<br/>emiliano/server · FastAPI"]
        disp["ExecutionDispatcher<br/>emiliano/core"]
        hist[("History<br/>SQLite: chats, messages")]
        cowork["Cowork<br/>see and operate windows"]
        server --> disp
        server --> hist
        server --> cowork
    end
    disp --> direct["Direct models<br/>emiliano/direct"]
    disp --> harn["Agent harnesses<br/>emiliano/harnesses"]
    direct --> ollama["Ollama<br/>local models"]
    direct --> apis["Cloud model APIs<br/>through litellm"]
    harn --> agents["Claude Code · Codex · OpenCode · Antigravity<br/>installed CLIs"]
    cowork --> screen["🖱️ Other windows<br/>mouse, keyboard, screen"]
    cli["CLI<br/>python -m emiliano.cli"] --> disp

    classDef input fill:#ede9fe,stroke:#7c3aed,color:#3b0764
    classDef ours fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef output fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef external fill:#f3f4f6,stroke:#6b7280,color:#374151
    classDef risk fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class user input
    class ui,server,disp,cowork,direct,harn,cli ours
    class hist output
    class ollama,apis,agents external
    class screen risk
    style desktop fill:#eff6ff,stroke:#2563eb
    style engine fill:#eff6ff,stroke:#2563eb
```

**Local only.** The server accepts only `127.0.0.1` / `localhost` hosts (`TrustedHostMiddleware`) and only the
desktop app's origins (`emiliano/server/security.py`). API keys are managed by `CredentialManager`
(`emiliano/direct/credentials.py`) and never logged unredacted.

## How a request is routed

`ExecutionDispatcher` (`emiliano/core/dispatcher.py`) checks these in order and uses the first that applies:

```mermaid
flowchart TD
    req["Request + routing policy"] --> h{"1. A harness<br/>named explicitly?"}
    h -->|yes| useh["that agent harness"]
    h -->|no| p{"2. A provider<br/>named explicitly?"}
    p -->|yes| usep["that model provider"]
    p -->|no| pol{"Policy?"}
    pol -->|local| loc["3. local model only (Ollama)"]
    pol -->|harness| har["4. prefer agent harnesses"]
    pol -->|api| api["5. remote API providers"]
    pol -->|"auto (default)"| auto{"6. Does the goal need tools:<br/>files, build, test, edit?"}
    auto -->|yes| har
    auto -->|no| loc2["local model first,<br/>then other ready options"]
    useh & usep & loc & har & api & loc2 --> fb{"Failed?"}
    fb -->|"yes, and safe to retry"| next["try the next candidate"]
    fb -->|no| done["✅ answer streamed back to the app"]

    classDef input fill:#ede9fe,stroke:#7c3aed,color:#3b0764
    classDef gate fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef ours fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef output fill:#dcfce7,stroke:#16a34a,color:#14532d
    class req input
    class h,p,pol,auto,fb gate
    class useh,usep,loc,har,api,loc2,next ours
    class done output
```

Only usable candidates count: a provider without credentials, or a harness whose CLI is not installed, is skipped.
A failure is not retried elsewhere when that could repeat work, for example after an agent already changed files.

## How a coding agent runs

Claude Code and Codex run over the **Agent Client Protocol** (ACP) when their ACP adapter is installed
(`claude-agent-acp`, `codex-acp`); OpenCode does when `opencode_acp_cmd: "opencode acp"` is set. Emiliano starts
the agent's ACP command and talks to it in structured messages (JSON-RPC over stdin/stdout). When the agent asks
to use a tool, the request is relayed over the chat WebSocket (`/api/chat`) to the Dock, and **you approve or
reject it**. No answer within 120 s counts as a rejection. Agents without ACP run as a plain CLI process whose
text output is streamed (`BaseHarness.run_task`); they get the `--dangerously-*` flags unless
`unattended_fallback: false`. Why ACP: [ADR 0001](adr/0001-use-acp-for-harnesses.md).

```mermaid
sequenceDiagram
    autonumber
    participant App as Desktop app (Dock)
    participant Srv as Engine server
    participant H as Harness (acp.py)
    participant Agent as Coding agent CLI
    App->>Srv: request
    Srv->>H: run on this harness
    H->>Agent: start ACP session, send the task
    Agent-->>H: progress, text
    H-->>App: streamed output
    Agent->>H: permission request (e.g. edit a file)
    H->>App: permission_request
    App->>H: allow once / reject (your choice)
    H->>Agent: decision
    Agent-->>H: result
    H-->>App: done
```

**Stopping.** Stop in the Dock (or Esc anywhere while a task runs) cancels the task, and the dispatcher then
calls `harness.cancel()` so the agent process stops too, not only the chat. Cancelling the wait alone would leave
the agent running in its worker thread.

```mermaid
flowchart LR
    stop["⛔ Stop / Esc"] --> srv["Server cancels the task<br/>pending permission requests → rejected"]
    srv --> disp["Dispatcher: harness.cancel()"]
    disp --> isacp{"Over ACP?"}
    isacp -->|yes| ask["send session/cancel"]
    ask --> grace{"Stopped within 3 s?"}
    grace -->|yes| ended["✅ agent ended cleanly"]
    grace -->|no| kill["kill the process tree"]
    isacp -->|"no (plain CLI)"| kill
    kill --> ended2["✅ agent ended"]

    classDef input fill:#ede9fe,stroke:#7c3aed,color:#3b0764
    classDef gate fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef ours fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef output fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef risk fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class stop input
    class isacp,grace gate
    class srv,disp,ask ours
    class kill risk
    class ended,ended2 output
```

## Cowork: operating other windows

```mermaid
flowchart LR
    pin["WindowPinManager<br/>pin the target window"] --> see["ScreenPerceiver<br/>list windows and UI elements"]
    see --> act{"Safety checks"}
    act -->|ok| do["ActionSynthesizer<br/>click, type (pyautogui)"]
    act -->|"Esc, cursor in a corner,<br/>or window changed"| stop["⛔ stop: SafetyInterruptedError"]
    do --> screen["🖱️ the pinned window"]

    classDef ours fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef gate fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef risk fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class pin,see,do ours
    class act gate
    class stop,screen risk
```

HTTP endpoints: `GET /api/cowork/windows`, `POST /api/cowork/pin`, `/unpin`, `GET /api/cowork/elements`,
`POST /api/cowork/click`, `/type`. **Esc must always stop it**: never weaken the emergency stop.

## Parts

| Part | Folder | What it does | Talks to |
| :--- | :--- | :--- | :--- |
| Desktop app | `apps/desktop` | Tauri 2 + React UI: chats, Dock (permission prompts), HUD overlay. Starts the bundled engine (sidecar); set `EMILIANO_EXTERNAL_ENGINE=1` to use one you started | Engine server |
| Protocol | `packages/protocol` | Message schemas shared by both sides: `models.py` (Python) and `types.ts` (TypeScript) | — |
| Server | `packages/engine/emiliano/server` | FastAPI on port 8765: `/health`, `/api/models`, cowork endpoints, WebSocket `/ws`; chat history at `/api/chats` and WebSocket `/api/chat` | Dispatcher, history, cowork |
| Dispatcher and registry | `packages/engine/emiliano/core` | Routing policy, capability registry, configuration, workspace and context | Direct, harnesses |
| Direct models | `packages/engine/emiliano/direct` | Unified client (litellm), Ollama manager, credentials | Ollama, cloud APIs |
| Harnesses | `packages/engine/emiliano/harnesses` | One adapter per coding agent; ACP client (`acp.py`); stopping a running agent (`cancel()`) | Agent CLIs |
| History | `packages/engine/emiliano/history` | SQLite store and API for chats and messages | Server |
| Cowork | `packages/engine/emiliano/cowork` | Window pinning, screen perception, mouse and keyboard actions | Other windows |
| CLI | `packages/engine/emiliano/cli.py` | Run requests, list harnesses, diagnostics, without the desktop app | Dispatcher |

## Where to change what

| To change... | Look in | Skill |
| :--- | :--- | :--- |
| Support another coding agent | `emiliano/harnesses/base.py` (+ `acp.py` if it speaks ACP) | `.agents/skills/add-harness-adapter` |
| A message between the app and the engine | `packages/protocol` (both files), then both sides | `.agents/skills/change-protocol` |
| How requests are routed | `emiliano/core/dispatcher.py` | `.agents/skills/review-change` |
| Cowork actions or their safety | `emiliano/cowork/` | `.agents/skills/review-change` |
| Chat history | `emiliano/history/` | `.agents/skills/review-change` |
