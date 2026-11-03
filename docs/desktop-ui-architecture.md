# Emiliano Desktop UI - Architecture & Design

## Executive Summary

**Goal:** Build a local-first, Claude Code-style desktop interface for Emiliano
**Tech Stack:** Tauri 2.0 + React/Vue + Python Backend (FastAPI)
**Architecture:** Sidecar pattern with HTTP communication
**Timeline:** 4-6 weeks for MVP

---

## State-of-the-Art Analysis: AI Coding UIs (2025-2026)

### 1. Claude Code Desktop ("Cowork")

**Key Features:**
- Visual interface with embedded browser preview
- No terminal required for non-technical users
- Live preview of UI changes
- Frontend Design plugin (November 2025) for aesthetic choices
- Screenshot-based verification loop

**Design Philosophy:**
- Keep users out of command line
- Tight feedback loop (write → screenshot → diff → refine)
- Multi-route product UI support

**Sources:**
- [A Designer's Guide to Claude Code](https://medium.com/design-bootcamp/a-designers-guide-to-organizing-ai-skills-and-tools-in-claude-code-f87477c35b82)
- [Claude Code for Designers](https://www.builder.io/blog/claude-code-for-designers)
- [How to Design Beautiful UIs With Claude Code](https://www.aidesigner.ai/blog/claude-code-frontend-design)

---

### 2. Cursor AI IDE

**Interface Layout:**
- **Chat panel:** 400-520px vertical strip (left or right side)
- **Composer:** Bottom of chat panel, grows upward
- **Chat history:** Agents sidebar (moved in Cursor 3.x, 2025)
- **Access:** Ctrl/⌘ + L for chat, Ctrl/⌘ + Alt/Option + L for history

**Key Features:**
- Previous Chats accessible via top-right button
- Chat history tied to project folder path
- Multiple agents in parallel across repos
- Past chat transcripts in @-mention search

**Pain Points:**
- Moving/renaming projects affects chat history access
- UI redesign in 3.x caused user confusion

**Sources:**
- [Cursor IDE Tutorials - Chat](https://cursorpractice.com/en/cursor-tutorials/getting-started/4-Chat)
- [New Cursor Interface](https://cursor.com/changelog/3-0)
- [Where is Chat History? - Forum](https://forum.cursor.com/t/where-is-chat-history/157455)

---

### 3. Windsurf (Codeium Cascade)

**Interface Design:**
- **Minimal, "Apple-polished" UI**
- File tree + omni-command palette
- **Agent Command Center:** Kanban-style dashboard for managing sessions
- **Cascade conversational interface:** Narrates reasoning as it works
- **Live previews:** See UI changes without browser switch

**Unique Features:**
- Image-to-code: Drop design mockup → generate UI code
- Persistent memory system (learns preferences)
- Best-in-class UX for non-power users

**Sources:**
- [Windsurf Review 2026](https://www.secondtalent.com/resources/windsurf-review/)
- [Windsurf AI Guide](https://myengineeringpath.dev/tools/windsurf-ai/)
- [Cursor vs Windsurf 2025](https://dev.to/blamsa0mine/cursor-vs-windsurf-2025-a-deep-dive-into-the-two-fastest-growing-ai-ides-2112)

---

### 4. AI Chat UI Design Patterns (2025-2026)

**Essential Components:**
1. **Streaming text** - Token-by-token rendering
2. **Markdown parsing** - Incremental, handles incomplete blocks
3. **Code blocks** - Syntax highlighting, copy button
4. **Auto-growing composer** - Expands with content
5. **Scroll-to-bottom** - Auto-scroll on new messages

**Technical Challenges:**
- Parse incomplete markdown during streaming
- Code blocks render as plain text until closing fence
- Apply syntax highlighting in second pass after block closes
- Buffer incomplete markdown before rendering

**Recommended Libraries:**
- **Vercel AI SDK** - Streaming support, React hooks
- **assistant-ui** - Pre-built AI chat components
- **Streamdown** - Markdown renderer for streaming AI content
- **shadcn/ui AI Response** - Auto-completes formatting during streaming

**Sources:**
- [8 Best UI Frameworks for AI Agents (2026)](https://fast.io/resources/best-ui-frameworks-ai-agents/)
- [UI Libraries for AI Chat Interfaces in 2026](https://alexander-lukashov.medium.com/the-overview-of-ui-libraries-for-ai-chat-interfaces-in-2026-146a1492114a)
- [AI Chat UI Best Practices](https://dev.to/greedy_reader/ai-chat-ui-best-practices-designing-better-llm-interfaces-18jj)

---

## Tauri + Python Architecture Analysis

### Approach 1: PyTauri (Direct Bindings)

**Pros:**
- No IPC overhead (uses Pyo3, Python → Rust bindings)
- Fast and secure
- API consistent with Rust Tauri
- Full-stack Python development

**Cons:**
- Newer project (2025 releases)
- Less mature ecosystem
- May require Rust knowledge for customization

**Use Case:** When maximum performance needed

**Sources:**
- [PyTauri IPC Documentation](https://pytauri.github.io/pytauri/0.4/usage/concepts/ipc/)

---

### Approach 2: Sidecar Pattern (HTTP/FastAPI) ✅ RECOMMENDED

**Architecture:**
```
┌─────────────────────────────────────────────────────────┐
│                  Tauri Frontend                         │
│              (React/Vue WebView)                        │
└───────────────────┬─────────────────────────────────────┘
                    │ HTTP (localhost:8008)
                    │
┌───────────────────▼─────────────────────────────────────┐
│           Python FastAPI Sidecar                        │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Existing Emiliano Engine                        │   │
│  │  - ExecutionDispatcher                           │   │
│  │  - ContextWindowManager                          │   │
│  │  - UnifiedLLMClient                              │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Pros:**
- Leverages existing Emiliano Python codebase (100% reuse)
- HTTP is well-understood, debuggable
- FastAPI supports WebSockets for streaming
- Easy to test backend independently
- Mature ecosystem (PyInstaller for packaging)

**Cons:**
- Slightly higher latency than direct bindings (~1-2ms)
- Requires process lifecycle management

**Implementation:**
1. FastAPI server in Python sidecar
2. WebSocket for streaming chat responses
3. REST API for commands (/context, /compact, /clear)
4. PyInstaller packages Python + dependencies

**Sources:**
- [Tauri v2 Python Server Sidecar Example](https://github.com/dieharders/example-tauri-v2-python-server-sidecar)
- [Vue + Tauri + FastAPI Sidecar Template](https://github.com/AlanSynn/vue-tauri-fastapi-sidecar-template)
- [Building Production-Ready Desktop LLM Apps](https://aiechoes.substack.com/p/building-production-ready-desktop)
- [Tauri Python Sidecar - Production Ready](https://github.com/matshoppenbrouwers/tauri-python-sidecar)

**Best Practices:**
- Use HTTP for commands, WebSocket for streaming
- Handle sidecar shutdown gracefully (no lingering processes)
- Place Python binary in `src-tauri/binaries/`
- Use Tauri v2 capability system for security
- Implement authenticated local transport

---

## Proposed Architecture: Emiliano Desktop

### Technology Stack

**Frontend:**
- **Framework:** React 18 + TypeScript
- **UI Library:** shadcn/ui (Tailwind CSS components)
- **Markdown:** react-markdown + remark-gfm
- **Code Highlighting:** Prism.js or Shiki
- **Streaming:** Vercel AI SDK or custom WebSocket
- **Build Tool:** Vite

**Backend (Sidecar):**
- **Framework:** FastAPI
- **WebSocket:** FastAPI WebSocket support
- **Engine:** Existing Emiliano Python packages
- **Packaging:** PyInstaller (single executable)

**Desktop Shell:**
- **Framework:** Tauri 2.0
- **IPC:** HTTP (REST) + WebSocket
- **Platform:** Windows, macOS, Linux

---

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Tauri Window                                   │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      React Frontend                                │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐   │  │
│  │  │   Sidebar   │  │  Chat Panel  │  │   Settings/Context     │   │  │
│  │  │             │  │              │  │       Panel            │   │  │
│  │  │ - Sessions  │  │ - Messages   │  │ - /context display     │   │  │
│  │  │ - History   │  │ - Composer   │  │ - Model selector       │   │  │
│  │  │ - New Chat  │  │ - Streaming  │  │ - Token usage          │   │  │
│  │  └─────────────┘  └──────────────┘  └────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────────────────────┘
                        │
                        │ HTTP/WebSocket (localhost:8008)
                        │
┌───────────────────────▼─────────────────────────────────────────────────┐
│                   Python FastAPI Sidecar                                 │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                     FastAPI Routes                                  │ │
│  │  - POST /api/chat/message      → Send user message                 │ │
│  │  - WS   /api/chat/stream       → Stream assistant response         │ │
│  │  - GET  /api/context           → Get context metrics               │ │
│  │  - POST /api/compact           → Trigger summarization             │ │
│  │  - POST /api/clear             → Clear conversation                │ │
│  │  - GET  /api/sessions          → List chat sessions                │ │
│  │  - POST /api/sessions          → Create new session                │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │              Existing Emiliano Engine (Reused 100%)                 │ │
│  │  - ExecutionDispatcher                                              │ │
│  │  - ContextWindowManager                                             │ │
│  │  - RecursiveSummarizer                                              │ │
│  │  - PersistentContextLoader                                          │ │
│  │  - ContextMetricsCollector                                          │ │
│  │  - UnifiedLLMClient                                                 │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                    Session Storage (SQLite)                         │ │
│  │  - Conversation history                                             │ │
│  │  - Message metadata                                                 │ │
│  │  - User preferences                                                 │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### UI Layout (Claude Code-Inspired)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Emiliano                                           [-] [□] [×]             │
├────────────┬───────────────────────────────────────────┬───────────────────┤
│            │                                           │                   │
│  SIDEBAR   │          CHAT PANEL                       │  CONTEXT PANEL    │
│  (240px)   │          (flex-grow)                      │  (320px, toggle)  │
│            │                                           │                   │
│ ┌────────┐ │  ┌─────────────────────────────────────┐ │ ┌───────────────┐ │
│ │ New    │ │  │ 🤖 Claude 3.7 Sonnet                │ │ │ CONTEXT USAGE │ │
│ │ Chat   │ │  │ 📊 45K / 180K tokens (25%)          │ │ │               │ │
│ └────────┘ │  └─────────────────────────────────────┘ │ │ [████░░░░░░]  │ │
│            │                                           │ │               │ │
│ Sessions   │  ┌─────────────────────────────────────┐ │ │ Breakdown:    │ │
│ ──────────│ │  │ 👤 User                             │ │ │ • History: 38K│ │
│ ● Context  │ │  │ How can I improve context mgmt?    │ │ │ • System: 2K  │ │
│   Mgmt     │ │  └─────────────────────────────────────┘ │ │ • Files: 5K   │ │
│            │ │                                           │ │               │ │
│ ○ UI Des...│ │  ┌─────────────────────────────────────┐ │ └───────────────┘ │
│            │ │  │ 🤖 Assistant                         │ │                   │
│ ○ Phase 2  │ │  │ I analyzed state-of-the-art...      │ │ ┌───────────────┐ │
│            │ │  │                                      │ │ │ SETTINGS      │ │
│ ────────── │ │  │ ```python                           │ │ │               │ │
│ + New Chat │ │  │ class RecursiveSummarizer:          │ │ │ Model:        │ │
│            │ │  │   ...                                │ │ │ [▼ Claude 3.7]│ │
│ ⚙️ Settings│ │  │ ```                                  │ │ │               │ │
│ 📊 Stats   │ │  │                                      │ │ │ Policy:       │ │
│            │ │  └─────────────────────────────────────┘ │ │ [▼ Auto]      │ │
│            │ │                                           │ │               │ │
│            │ │  ┌─────────────────────────────────────┐ │ │ Context:      │ │
│            │ │  │ 👤 User                             │ │ │ ☑ Summarize   │ │
│            │ │  │ Can you show /context?              │ │ │ ☑ Persistent  │ │
│            │ │  └─────────────────────────────────────┘ │ └───────────────┘ │
│            │ │                                           │                   │
│            │ │  ┌─────────────────────────────────────┐ │                   │
│            │ │  │ 🤖 Assistant ⚡ Typing...           │ │                   │
│            │ │  │ ▋                                    │ │                   │
│            │ │  └─────────────────────────────────────┘ │                   │
│            │ │                                           │                   │
│            │ │  ┌─────────────────────────────────────┐ │                   │
│            │ │  │ 💬 Type your message...             │ │                   │
│            │ │  │                                      │ │                   │
│            │ │  │ [Shift+Enter for newline]     [📎]│ │                   │
│            │ │  └─────────────────────────────────────┘ │                   │
│            │ │  [Send] [/commands ▼] [⚙️]               │                   │
└────────────┴───────────────────────────────────────────┴───────────────────┘
```

**Key UI Elements:**

1. **Sidebar (240px, collapsible)**
   - Session list (like Cursor chat history)
   - Active session highlighted
   - New chat button
   - Settings & stats at bottom

2. **Chat Panel (Main, flex-grow)**
   - Model indicator at top
   - Token usage summary bar
   - Message list (scrollable)
   - Markdown rendering (incremental for streaming)
   - Code blocks with syntax highlighting
   - Auto-growing composer at bottom
   - Command shortcuts (/context, /compact, /clear)

3. **Context Panel (320px, toggle with Ctrl+K)**
   - Real-time context usage (from ContextMetricsCollector)
   - Visual progress bar
   - Token breakdown
   - Model/policy settings
   - Context feature toggles

---

### Data Flow

#### 1. Send Message Flow

```
User types message → Click Send
  ↓
Frontend: POST /api/chat/message
  {
    "session_id": "uuid",
    "message": "How do I...",
    "settings": { "model": "claude-3-7-sonnet", "policy": "auto" }
  }
  ↓
Backend FastAPI: Receive message
  ↓
Save to SQLite conversation history
  ↓
Execute via ExecutionDispatcher
  ↓
WebSocket stream response chunks
  ws.send({ "type": "chunk", "content": "token" })
  ws.send({ "type": "chunk", "content": " by" })
  ws.send({ "type": "chunk", "content": " token" })
  ws.send({ "type": "done", "metadata": {...} })
  ↓
Frontend: Render incrementally
  - Parse markdown as it arrives
  - Buffer incomplete code blocks
  - Apply syntax highlighting on completion
  - Auto-scroll to bottom
```

#### 2. Context Metrics Flow

```
User clicks "Show Context" or presses Ctrl+Shift+C
  ↓
Frontend: GET /api/context?session_id=uuid
  ↓
Backend: ContextMetricsCollector.collect_metrics(...)
  ↓
Return JSON:
  {
    "total_tokens": 45234,
    "history_tokens": 38000,
    "system_tokens": 2234,
    "file_tokens": 5000,
    "usage_percentage": 25.1,
    "status": "GOOD"
  }
  ↓
Frontend: Display in Context Panel
  - Update progress bar
  - Show breakdown
  - Update status indicator
```

#### 3. Session Management Flow

```
App startup:
  ↓
Frontend: GET /api/sessions
  ↓
Backend: Query SQLite for recent sessions
  ↓
Return: [
  { "id": "uuid1", "title": "Context Management", "last_message": "...", "timestamp": "..." },
  { "id": "uuid2", "title": "UI Design", ... }
]
  ↓
Frontend: Populate sidebar session list
  ↓
User clicks session → Load messages → Render in chat panel
```

---

### API Specification

#### REST Endpoints

```typescript
// Sessions
GET    /api/sessions                  → List all sessions
POST   /api/sessions                  → Create new session
GET    /api/sessions/:id              → Get session details
DELETE /api/sessions/:id              → Delete session
GET    /api/sessions/:id/messages     → Get session messages

// Chat
POST   /api/chat/message              → Send message (initiates stream)
POST   /api/chat/clear                → Clear current session
POST   /api/chat/compact              → Trigger summarization

// Context
GET    /api/context                   → Get context metrics
GET    /api/context/persistent        → Get persistent context files

// Settings
GET    /api/settings                  → Get current settings
PUT    /api/settings                  → Update settings

// Health
GET    /api/health                    → Health check
```

#### WebSocket

```typescript
WS /api/chat/stream

// Client → Server
{
  "type": "message",
  "session_id": "uuid",
  "content": "User message",
  "settings": { "model": "...", "policy": "..." }
}

// Server → Client (streaming)
{
  "type": "chunk",
  "content": "token"
}

{
  "type": "tool_use",
  "tool": "bash",
  "input": "ls -la"
}

{
  "type": "tool_result",
  "tool": "bash",
  "output": "..."
}

{
  "type": "context_update",
  "tokens": 45234,
  "status": "GOOD"
}

{
  "type": "done",
  "metadata": {
    "tokens_used": 1234,
    "model": "claude-3-7-sonnet",
    "duration_ms": 3500
  }
}

{
  "type": "error",
  "message": "Context window exceeded",
  "code": "CONTEXT_OVERFLOW"
}
```

---

### Component Structure

```
packages/desktop/
├── src-tauri/                    # Tauri Rust backend
│   ├── binaries/
│   │   ├── emiliano-x86_64-pc-windows-msvc.exe
│   │   ├── emiliano-aarch64-apple-darwin
│   │   └── emiliano-x86_64-unknown-linux-gnu
│   ├── src/
│   │   ├── main.rs              # Tauri app entry
│   │   └── sidecar.rs           # Sidecar lifecycle management
│   ├── tauri.conf.json          # Tauri configuration
│   └── Cargo.toml
│
├── src/                          # React frontend
│   ├── components/
│   │   ├── chat/
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── MessageList.tsx
│   │   │   ├── Message.tsx      # Single message (user/assistant)
│   │   │   ├── Composer.tsx     # Input composer
│   │   │   └── StreamingMessage.tsx
│   │   ├── sidebar/
│   │   │   ├── Sidebar.tsx
│   │   │   ├── SessionList.tsx
│   │   │   └── SessionItem.tsx
│   │   ├── context/
│   │   │   ├── ContextPanel.tsx
│   │   │   ├── TokenUsageBar.tsx
│   │   │   └── ContextBreakdown.tsx
│   │   ├── settings/
│   │   │   └── SettingsPanel.tsx
│   │   └── ui/                   # shadcn/ui components
│   │       ├── button.tsx
│   │       ├── input.tsx
│   │       └── ...
│   ├── hooks/
│   │   ├── useChat.ts            # Chat state & WebSocket
│   │   ├── useSessions.ts        # Session management
│   │   ├── useContext.ts         # Context metrics
│   │   └── useSettings.ts        # Settings state
│   ├── lib/
│   │   ├── api.ts                # API client
│   │   ├── websocket.ts          # WebSocket manager
│   │   └── markdown.ts           # Markdown streaming utils
│   ├── App.tsx
│   └── main.tsx
│
└── packages/engine/              # Python backend (EXISTING)
    └── emiliano_desktop/         # NEW: FastAPI wrapper
        ├── __init__.py
        ├── main.py               # FastAPI app entry
        ├── api/
        │   ├── chat.py           # Chat endpoints
        │   ├── sessions.py       # Session endpoints
        │   ├── context.py        # Context endpoints
        │   └── websocket.py      # WebSocket handler
        ├── models/
        │   ├── session.py        # SQLAlchemy models
        │   └── message.py
        └── database.py           # SQLite setup
```

---

### Phase 1: MVP Implementation Plan

#### Week 1: Backend Foundation
- [x] Phase 1 context components (DONE)
- [ ] Create FastAPI app structure
- [ ] Implement WebSocket streaming
- [ ] Add REST endpoints (/chat, /sessions, /context)
- [ ] SQLite session storage
- [ ] Package with PyInstaller

#### Week 2: Tauri Setup
- [ ] Initialize Tauri project
- [ ] Configure sidecar permissions
- [ ] Implement sidecar lifecycle (start, monitor, shutdown)
- [ ] Test Python sidecar execution
- [ ] Cross-platform build testing

#### Week 3: React Frontend
- [ ] Setup Vite + React + TypeScript
- [ ] Install shadcn/ui components
- [ ] Build ChatPanel component
- [ ] Build Sidebar component
- [ ] Implement WebSocket streaming
- [ ] Markdown rendering with code blocks

#### Week 4: Integration & Polish
- [ ] Connect frontend ↔ backend
- [ ] Test streaming chat
- [ ] Add ContextPanel
- [ ] Session persistence
- [ ] Settings panel
- [ ] Error handling
- [ ] Auto-updater setup

#### Week 5-6: Testing & Release
- [ ] Cross-platform testing (Windows, macOS, Linux)
- [ ] Performance optimization
- [ ] UI/UX polish
- [ ] Documentation
- [ ] Release build & distribution

---

### Technical Decisions

| Decision | Choice | Rationale |
|:---|:---|:---|
| **Frontend Framework** | React + TypeScript | Mature, large ecosystem, TypeScript safety |
| **UI Library** | shadcn/ui | Beautiful, customizable, Tailwind-based |
| **Markdown** | react-markdown | Best React markdown renderer |
| **Code Highlighting** | Shiki | Better syntax highlighting than Prism |
| **Streaming** | WebSocket | Better for bidirectional, long-lived connections |
| **Backend** | FastAPI | Async, WebSocket support, existing Emiliano code |
| **Sidecar Pattern** | HTTP + WS | Reuse existing Python, easier debugging |
| **Database** | SQLite | Local-first, no server needed, cross-platform |
| **Packaging** | PyInstaller | Proven, single executable, cross-platform |
| **Desktop Shell** | Tauri 2.0 | Lightweight, secure, cross-platform |

---

### Comparison: PyTauri vs Sidecar

| Aspect | PyTauri | Sidecar (HTTP/WS) |
|:---|:---|:---|
| **Performance** | Faster (no IPC) | Slightly slower (~1-2ms) |
| **Code Reuse** | Requires bindings | 100% reuse existing code |
| **Debugging** | Harder (Rust + Python) | Easy (HTTP is standard) |
| **Maturity** | New (2025) | Mature, proven |
| **Complexity** | Medium-High | Low-Medium |
| **Recommended for** | Greenfield projects | Existing Python codebases |

**Decision: Sidecar pattern** - Maximizes code reuse, easier debugging, proven approach.

---

### Next Steps

1. ✅ Complete Phase 1 context integration (dispatcher, CLI)
2. 🔨 Create FastAPI backend wrapper
3. 🔨 Initialize Tauri project
4. 🔨 Build React frontend
5. 🔨 Integrate & test
6. 🚀 Package & release

---

## References

### UI/UX Design
- [A Designer's Guide to Claude Code](https://medium.com/design-bootcamp/a-designers-guide-to-organizing-ai-skills-and-tools-in-claude-code-f87477c35b82)
- [Cursor IDE Tutorials](https://cursorpractice.com/en/cursor-tutorials/getting-started/4-Chat)
- [Windsurf Review 2026](https://www.secondtalent.com/resources/windsurf-review/)
- [AI Chat UI Best Practices](https://dev.to/greedy_reader/ai-chat-ui-best-practices-designing-better-llm-interfaces-18jj)
- [UI Libraries for AI Chat Interfaces 2026](https://alexander-lukashov.medium.com/the-overview-of-ui-libraries-for-ai-chat-interfaces-in-2026-146a1492114a)

### Tauri + Python
- [Tauri v2 Python Server Sidecar Example](https://github.com/dieharders/example-tauri-v2-python-server-sidecar)
- [Vue + Tauri + FastAPI Template](https://github.com/AlanSynn/vue-tauri-fastapi-sidecar-template)
- [Building Production-Ready Desktop LLM Apps](https://aiechoes.substack.com/p/building-production-ready-desktop)
- [Tauri Python Sidecar - Production](https://github.com/matshoppenbrouwers/tauri-python-sidecar)
- [PyTauri IPC Documentation](https://pytauri.github.io/pytauri/0.4/usage/concepts/ipc/)

---

**Document Version:** 1.0
**Created:** 2026-11-02
**Next Update:** After MVP completion
