# 0005. Local-First Workspaces, Project Directories, Persistent Artifacts, and Reasoning Chains

- **Status:** Accepted (2026-11-17)
- **Date:** 2026-11-17
- **Target Systems:** Emiliano Engine Daemon, Desktop UI (React/Tauri), History Store (SQLite)

---

## 1. Context

Desktop AI assistants frequently suffer from three major design flaws:
1. **Cloud Account Lock-in:** Forcing users into remote cloud databases or SaaS accounts, compromising sensitive local codebase confidentiality.
2. **Conflated Navigation & Identity Loss:** Overloading sidebar navigation by redirecting "Projects" or "Artifacts" to secondary views (such as general MCP connects or agent skills), failing to provide dedicated workspaces.
3. **Stateless Deliverables & Hidden Reasoning:** Generated deliverables (architecture diagrams, execution plans, code manifests) are lost in conversational scrollback without persistent indexing or filesystem association; meanwhile, frontier thinking models (DeepSeek-R1, Qwen 2.5/3.5, Claude 3.7 Sonnet) either fail to stream their internal reasoning or pollute the final answer text with raw tokens.

---

## 2. Decision

We implement a unified, local-first workspace architecture comprising:

### 1. Dedicated SQLite Schema & Foreign-Key Integrity (`store.py`)
* **Local-First Database:** Stored at `~/.emiliano/history.db` with SQLite WAL mode and strict `PRAGMA foreign_keys=ON`.
* **`projects` Table:**
  * `id TEXT PRIMARY KEY`: Unique project identifier (e.g. `oracliom-main`, `plaatoos-outreach`).
  * `name TEXT NOT NULL`: Project display title.
  * `description TEXT`: Functional summary.
  * `root_path TEXT NOT NULL`: Absolute local filesystem directory path binding the project to an on-disk folder.
  * `system_prompt TEXT`: Custom instructions and invariants applied to all runs in this project.
  * `created_at`, `updated_at`: ISO 8601 timestamps.
* **`chats` Foreign Key Migration:**
  * Non-destructive migration: `ALTER TABLE chats ADD COLUMN project_id TEXT REFERENCES projects(id)`.
  * Scoping: Chats are associated with a project, isolating conversational history per codebase.
* **`artifacts` Table:**
  * `id TEXT PRIMARY KEY`: Deliverable ID.
  * `chat_id TEXT REFERENCES chats(id)`: Originating conversation.
  * `project_id TEXT REFERENCES projects(id)`: Project workspace ownership.
  * `title TEXT NOT NULL`: Human-readable deliverable title.
  * `kind TEXT NOT NULL`: `code`, `diagram`, `plan`, `report`, or `markdown`.
  * `content TEXT NOT NULL`: Deliverable payload (Mermaid syntax, markdown, source code).
  * `file_path TEXT`: Optional path to on-disk mirrored file.
  * `created_at`, `updated_at`: ISO 8601 timestamps.

### 2. Project Directory Scoping & Dispatcher Execution (`api.py`, `dispatcher.py`)
* **Directory Binding:** When a chat has `project_id`, `api.py` resolves the project's `root_path` and forwards `workspace=project.root_path` to `ExecutionDispatcher.execute_task`.
* **Guideline Injection:** If the project defines a `system_prompt`, it is dynamically prepended to the task messages as a system message.
* **OS Interop:**
  * `POST /api/projects/{id}/open-folder`: Invokes native OS explorer (`os.startfile` on Windows, `open`/`xdg-open` on Unix) to display the project folder.
  * `POST /api/artifacts/{id}/open`: Directly launches the mirrored deliverable file in the user's default editor.

### 3. Frontier Thinking Stream & Live UI Rendering (`Dock.tsx`)
* **Reasoning Protocol:** Streaming WebSocket chunks emit `{"type": "reasoning", "content": "..."}` as well as inline `<think>...</think>` tags.
* **Live Thought Card:**
  * While `pending: true`, renders an animated cyan card with spinning brain/sparkles icon: `Thinking process in progress… [Streaming]`.
  * Upon turn completion (`pending: false`), collapses automatically into `Thought process (completed)` with an interactive toggle chevron, ensuring the final answer text is clean and legible while preserving the audit trail.

### 4. Dedicated UI Sub-Panels
* **Projects Sub-Panel:** Lists local workspaces, shows folder paths, provides quick "Open in Explorer" triggers, filter badges, and an inline "+ Add Project" modal.
* **Artifacts Sub-Panel & Gallery:** Provides category chips (`All`, `Diagram`, `Plan`, `Code`, `Doc`), shows project ownership tags, and opens the `ArtifactPreviewModal` with rendered markdown, syntax highlighting, and copy utilities.

```
+-----------------------------------------------------------------------------------------+
|                                    EMILIANO DESKTOP DOCK                                |
|  [Home | Cowork]                                                                        |
|  - Projects Sub-Panel: [Oracliom Main] (📁 C:/.../Oracliom)                             |
|                        [PlaatoOS Outreach] (📁 C:/.../emiliano-cowork-plaatoos)         |
|  - Artifacts Gallery:  [Multi-Channel Pipeline] | [Campaign Manifest] | [Outreach Analysis]|
|  - Chat Stream:        [Thinking Process in Progress... 🧠]                             |
|                        [Assistant Response Text & Artifact Extractors]                  |
+-----------------------------------------------------------------------------------------+
                                          | WebSocket / REST IPC
                                          v
+-----------------------------------------------------------------------------------------+
|                                EMILIANO ENGINE DAEMON (FastAPI)                         |
|  - /api/projects, /api/artifacts, /api/chats                                            |
|  - WebSocket /ws/chat: Scopes workspace root_path & injects system_prompt               |
|  - SQLite Store (~/.emiliano/history.db): Foreign key relational integrity              |
+-----------------------------------------------------------------------------------------+
```

---

## 3. Consequences

* **Positive:**
  * Clean architectural separation: Projects and Artifacts are first-class citizens.
  * Transparent codebase binding: Workspaces explicitly define which on-disk directory tools operate in.
  * Zero cloud telemetry/storage: Confidential enterprise projects remain local-first.
  * Enhanced UX: Reasoning models show real-time thought formation without polluting the final message.
* **Negative / Trade-offs:**
  * Local folder paths are host OS specific (handled via normalized path resolution and `os.name` branching).
