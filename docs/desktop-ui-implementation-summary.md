# Emiliano Desktop UI - Research Findings & Proposed Architecture

## Executive Summary

**Status:** ✅ Research Complete, Architecture Designed
**Recommendation:** Tauri 2.0 + React + Python FastAPI Sidecar
**Code Reuse:** 100% of existing Emiliano engine
**Timeline:** 4-6 weeks for MVP

---

## Research Findings: State-of-the-Art (2025-2026)

### 1. Claude Code Desktop ("Cowork")

**What They Did Right:**
- Visual interface with **live browser preview** embedded
- **No terminal required** - friendly for non-developers
- **Frontend Design plugin** (Nov 2025) - AI makes aesthetic choices before coding
- **Screenshot-based feedback loop**: write → screenshot → diff → refine
- **Multi-route product UI** support (dashboards, settings, etc.)

**Key Takeaway:** Tight feedback loop + visual preview = better UX

**Sources:**
- [A Designer's Guide to Claude Code](https://medium.com/design-bootcamp/a-designers-guide-to-organizing-ai-skills-and-tools-in-claude-code-f87477c35b82)
- [Claude Code for Designers](https://www.builder.io/blog/claude-code-for-designers)

---

### 2. Cursor AI IDE

**Interface Layout:**
- **Chat panel:** 400-520px vertical strip (side panel)
- **Composer:** Bottom of chat, grows upward with content
- **Chat history:** Moved to "Agents sidebar" in Cursor 3.x (2025)
- **Keyboard shortcuts:** Ctrl/⌘ + L (chat), Ctrl/⌘ + Alt + L (history)

**Key Features:**
- **Session persistence** - chat history tied to project folder
- **Multiple parallel agents** across repos
- **@-mention search** includes past chat transcripts

**Pain Points:**
- Moving/renaming projects breaks chat history access
- Major UI redesign in 3.x confused users

**Key Takeaway:** Side panel + keyboard shortcuts + persistent sessions

**Sources:**
- [Cursor IDE Chat Tutorial](https://cursorpractice.com/en/cursor-tutorials/getting-started/4-Chat)
- [New Cursor Interface 3.0](https://cursor.com/changelog/3-0)
- [Cursor Forum - Chat History Issues](https://forum.cursor.com/t/where-is-chat-history/157455)

---

### 3. Windsurf (Codeium Cascade)

**Design Philosophy:**
- **Minimal, "Apple-polished" UI** - clean, simple, intuitive
- **Agent Command Center** - Kanban-style dashboard for managing sessions
- **Cascade narrates reasoning** as it works (transparency)
- **Live previews** - see UI changes without browser switch
- **Best-in-class UX for non-power users**

**Unique Features:**
- **Image-to-code:** Drop mockup → generates UI code
- **Persistent memory:** Actually learns user preferences
- **Multi-file awareness:** Understands codebase relationships

**Key Takeaway:** Simplicity + transparency + visual feedback

**Sources:**
- [Windsurf Review 2026](https://www.secondtalent.com/resources/windsurf-review/)
- [Windsurf AI Guide](https://myengineeringpath.dev/tools/windsurf-ai/)
- [Cursor vs Windsurf Comparison](https://dev.to/blamsa0mine/cursor-vs-windsurf-2025-a-deep-dive-into-the-two-fastest-growing-ai-ides-2112)

---

### 4. AI Chat UI Design Patterns (2025-2026)

**Essential Components:**
1. **Streaming text** - Token-by-token rendering
2. **Incremental markdown parsing** - Handle incomplete blocks gracefully
3. **Code blocks** - Syntax highlighting + copy button
4. **Auto-growing composer** - Expands as user types
5. **Auto-scroll** - Follow conversation bottom

**Technical Challenges & Solutions:**
- **Challenge:** Parse incomplete markdown during streaming
- **Solution:** Buffer incomplete blocks, defer rendering until closing fence

- **Challenge:** Code blocks render as plain text during streaming
- **Solution:** Apply syntax highlighting in second pass after block closes

- **Challenge:** Bold/italic/code formatting broken mid-stream
- **Solution:** Auto-complete incomplete formatting (Streamdown library)

**Recommended Tech:**
- **Vercel AI SDK** - React hooks for streaming
- **assistant-ui** - Pre-built AI chat components
- **Streamdown** - Markdown renderer optimized for streaming
- **shadcn/ui AI Response** - Auto-completes formatting

**Key Takeaway:** Streaming requires special handling of incomplete markdown

**Sources:**
- [8 Best UI Frameworks for AI Agents (2026)](https://fast.io/resources/best-ui-frameworks-ai-agents/)
- [UI Libraries for AI Chat 2026](https://alexander-lukashov.medium.com/the-overview-of-ui-libraries-for-ai-chat-interfaces-in-2026-146a1492114a)
- [AI Chat UI Best Practices](https://dev.to/greedy_reader/ai-chat-ui-best-practices-designing-better-llm-interfaces-18jj)

---

## Tauri + Python Architecture Options

### Option 1: PyTauri (Direct Bindings)

**How It Works:**
- Python bindings to Rust via Pyo3
- **No IPC overhead** - direct function calls
- API consistent with Rust Tauri

**Pros:**
- ✅ Maximum performance (no HTTP latency)
- ✅ Secure (no network layer)
- ✅ Fast (direct Rust ↔ Python)

**Cons:**
- ❌ New project (2025 releases, less mature)
- ❌ Requires Rust knowledge for customization
- ❌ Would need to refactor existing Emiliano code

**Use Case:** Greenfield projects needing max performance

**Source:** [PyTauri IPC Documentation](https://pytauri.github.io/pytauri/0.4/usage/concepts/ipc/)

---

### Option 2: Sidecar Pattern (HTTP + FastAPI) ✅ RECOMMENDED

**How It Works:**
```
Tauri Frontend (React)
       ↕ HTTP/WebSocket (localhost:8008)
Python FastAPI Sidecar
       ↓
Existing Emiliano Engine (100% reuse)
```

**Pros:**
- ✅ **100% code reuse** - existing Emiliano engine unchanged
- ✅ **Easy debugging** - HTTP is standard, well-understood
- ✅ **Independent testing** - test backend without frontend
- ✅ **Mature ecosystem** - FastAPI, PyInstaller proven
- ✅ **WebSocket support** - perfect for streaming
- ✅ **Cross-platform** - PyInstaller bundles everything

**Cons:**
- ❌ Slightly higher latency (~1-2ms per request)
- ❌ Requires process lifecycle management

**Best Practices (from research):**
1. Use HTTP for commands, WebSocket for streaming
2. Place Python binary in `src-tauri/binaries/`
3. Handle sidecar shutdown gracefully (no lingering processes)
4. Use Tauri v2 capability system for security
5. Implement authenticated local transport

**Production-Ready Examples:**
- [Tauri v2 Python Server Sidecar](https://github.com/dieharders/example-tauri-v2-python-server-sidecar)
- [Vue + Tauri + FastAPI Template](https://github.com/AlanSynn/vue-tauri-fastapi-sidecar-template)
- [Production Tauri Python Sidecar](https://github.com/matshoppenbrouwers/tauri-python-sidecar)

**Sources:**
- [Building Production-Ready Desktop LLM Apps](https://aiechoes.substack.com/p/building-production-ready-desktop)
- [Tauri Sidecar Best Practices](https://evilmartians.com/chronicles/making-desktop-apps-with-revved-up-potential-rust-tauri-sidecar)

---

## Recommended Architecture

### Technology Stack

| Layer | Technology | Rationale |
|:---|:---|:---|
| **Desktop Shell** | Tauri 2.0 | Lightweight (vs Electron), secure, cross-platform |
| **Frontend** | React 18 + TypeScript | Mature, large ecosystem, type safety |
| **UI Components** | shadcn/ui | Beautiful, customizable, Tailwind CSS |
| **Markdown** | react-markdown + remark-gfm | Best React markdown renderer |
| **Code Highlighting** | Shiki | Better than Prism, VS Code-quality |
| **Streaming** | WebSocket (FastAPI) | Bidirectional, perfect for chat |
| **Backend** | FastAPI + Python | Async, WebSocket, existing code |
| **Engine** | **Existing Emiliano** | 100% reuse, zero refactor |
| **Packaging** | PyInstaller | Single executable, cross-platform |
| **Database** | SQLite | Local-first, no server, portable |

---

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Tauri Desktop Window                        │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │               React Frontend (WebView)                      │ │
│  │                                                             │ │
│  │  ┌──────────┐  ┌─────────────┐  ┌──────────────────────┐  │ │
│  │  │ Sidebar  │  │ Chat Panel  │  │  Context Panel       │  │ │
│  │  │          │  │             │  │                      │  │ │
│  │  │ Sessions │  │  Messages   │  │  Token Usage (live)  │  │ │
│  │  │ History  │  │  Streaming  │  │  Settings            │  │ │
│  │  │ New Chat │  │  Composer   │  │  Model Selector      │  │ │
│  │  └──────────┘  └─────────────┘  └──────────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
└───────────────────────┬──────────────────────────────────────────┘
                        │
                        │ HTTP REST + WebSocket
                        │ (localhost:8008)
                        │
┌───────────────────────▼──────────────────────────────────────────┐
│               Python FastAPI Sidecar Process                     │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                   FastAPI REST API                          │ │
│  │  POST /api/chat/message    → Send user message             │ │
│  │  WS   /api/chat/stream     → Stream assistant response     │ │
│  │  GET  /api/context         → Get context metrics           │ │
│  │  POST /api/compact         → Trigger summarization         │ │
│  │  GET  /api/sessions        → List chat sessions            │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │          Existing Emiliano Engine (NO CHANGES!)             │ │
│  │  ✅ ExecutionDispatcher                                     │ │
│  │  ✅ ContextWindowManager                                    │ │
│  │  ✅ RecursiveSummarizer                                     │ │
│  │  ✅ PersistentContextLoader                                 │ │
│  │  ✅ ContextMetricsCollector                                 │ │
│  │  ✅ UnifiedLLMClient                                        │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              SQLite Database (Session Storage)              │ │
│  │  - Conversation history                                     │ │
│  │  - User preferences                                         │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

### UI Layout (Inspired by Claude Code + Cursor + Windsurf)

**Left Sidebar (240px, collapsible):**
- ● Active session (highlighted)
- ○ Previous sessions (chronological)
- "+ New Chat" button
- ⚙️ Settings (bottom)

**Main Chat Panel (flex-grow):**
- Model indicator + token usage bar (top)
- Scrollable message list
  - User messages (right-aligned, blue)
  - Assistant messages (left-aligned, gray)
  - Streaming indicator (pulsing cursor)
  - Code blocks with syntax highlighting
  - Copy buttons
- Auto-growing composer (bottom)
  - "Type your message..." placeholder
  - Shift+Enter for newline
  - Command shortcuts (/context, /compact, /clear)
  - Attach button (future: files/images)

**Right Context Panel (320px, toggle with Ctrl+K):**
- **Context Usage Widget**
  - Progress bar visualization
  - Token breakdown (history, system, files, etc.)
  - Status indicator (GOOD/HIGH/CRITICAL)
- **Settings**
  - Model dropdown
  - Execution policy dropdown
  - Context feature toggles
- **Quick Actions**
  - /context button
  - /compact button
  - /clear button

---

### Data Flow Example: Sending a Message

```
1. User types "How do I implement X?" in composer
   ↓
2. Click "Send" or press Enter
   ↓
3. Frontend:
   - Add user message to UI (optimistic update)
   - Create WebSocket connection to /api/chat/stream
   - Send: { type: "message", session_id: "...", content: "..." }
   ↓
4. Backend FastAPI:
   - Receive via WebSocket
   - Save message to SQLite
   - Call ExecutionDispatcher.execute_task(...)
   - Stream response chunks via WebSocket
   ↓
5. Backend streams:
   ws.send({ type: "chunk", content: "To" })
   ws.send({ type: "chunk", content: " implement" })
   ws.send({ type: "chunk", content: " X" })
   ws.send({ type: "chunk", content: ", you" })
   ...
   ws.send({ type: "done", metadata: { tokens: 1234, duration_ms: 2500 } })
   ↓
6. Frontend:
   - Receive chunks via WebSocket
   - Append to message buffer
   - Parse markdown incrementally
   - Render in real-time
   - Auto-scroll to bottom
   - Show "done" indicator when complete
```

---

### Why This Approach Wins

| Requirement | Solution | Benefit |
|:---|:---|:---|
| **Local-first** | SQLite + no cloud dependencies | Privacy, works offline |
| **Code reuse** | Sidecar wraps existing engine | Zero refactoring needed |
| **Fast iteration** | HTTP APIs easily testable | Debug backend independently |
| **Streaming chat** | WebSocket + incremental markdown | Real-time, like ChatGPT |
| **Cross-platform** | Tauri + PyInstaller | Windows, macOS, Linux |
| **Beautiful UI** | shadcn/ui + Tailwind | Modern, customizable |
| **Context visibility** | Live token usage panel | Users see what AI sees |
| **Session persistence** | SQLite chat history | Never lose conversations |

---

## Implementation Roadmap

### Phase 1: Backend Foundation (Week 1)

**Goal:** FastAPI wrapper around existing Emiliano engine

**Tasks:**
- [ ] Create `packages/engine/emiliano_desktop/` module
- [ ] Implement FastAPI app with routes:
  - POST `/api/chat/message`
  - WS `/api/chat/stream`
  - GET `/api/context`
  - POST `/api/compact`
  - GET `/api/sessions`
- [ ] Integrate ContextWindowManager, RecursiveSummarizer, etc.
- [ ] SQLite session storage (SQLAlchemy models)
- [ ] WebSocket streaming implementation
- [ ] Test with `curl` and `wscat`

**Deliverable:** Working FastAPI backend, testable independently

---

### Phase 2: Tauri Setup (Week 2)

**Goal:** Tauri desktop shell that launches Python sidecar

**Tasks:**
- [ ] `npm create tauri-app@latest`
- [ ] Configure `tauri.conf.json`:
  - Sidecar binary paths
  - Permissions (shell, fs, network)
  - Window size, title, icon
- [ ] Implement sidecar lifecycle in `src-tauri/src/main.rs`:
  - Start Python server on app launch
  - Health check polling
  - Graceful shutdown on app close
- [ ] Package Python backend with PyInstaller
- [ ] Test cross-platform builds

**Deliverable:** Tauri app that starts/stops Python backend

---

### Phase 3: React Frontend (Week 3)

**Goal:** Beautiful chat UI with streaming

**Tasks:**
- [ ] Setup Vite + React + TypeScript
- [ ] Install shadcn/ui: `npx shadcn-ui@latest init`
- [ ] Build components:
  - `ChatPanel.tsx`
  - `MessageList.tsx`
  - `Message.tsx` (with markdown rendering)
  - `Composer.tsx` (auto-growing textarea)
  - `Sidebar.tsx`
  - `SessionList.tsx`
  - `ContextPanel.tsx`
- [ ] Implement hooks:
  - `useChat.ts` (WebSocket streaming)
  - `useSessions.ts` (session CRUD)
  - `useContext.ts` (metrics polling)
- [ ] Markdown + code highlighting (Shiki)
- [ ] Streaming message rendering

**Deliverable:** Functional chat UI (mocked backend OK)

---

### Phase 4: Integration (Week 4)

**Goal:** Connect frontend ↔ backend, end-to-end flow

**Tasks:**
- [ ] Connect React to FastAPI via HTTP/WS
- [ ] Test streaming chat flow
- [ ] Implement session persistence
- [ ] Add ContextPanel with live metrics
- [ ] Settings panel (model, policy selection)
- [ ] Error handling (network errors, context overflow, etc.)
- [ ] Loading states, spinners

**Deliverable:** Fully functional desktop app (local testing)

---

### Phase 5: Polish & Release (Week 5-6)

**Goal:** Production-ready, distributable app

**Tasks:**
- [ ] Cross-platform testing (Windows, macOS, Linux)
- [ ] Performance optimization (lazy loading, virtualization)
- [ ] UI/UX polish (animations, transitions, dark mode)
- [ ] Keyboard shortcuts (Ctrl+K, Ctrl+L, etc.)
- [ ] Auto-updater setup (Tauri updater)
- [ ] Documentation (user guide, troubleshooting)
- [ ] Build & sign installers (.exe, .dmg, .AppImage)
- [ ] Release v1.0.0

**Deliverable:** Distributed desktop app, ready for users

---

## Comparison: Sidecar vs PyTauri

| Aspect | Sidecar (HTTP/WS) | PyTauri (Bindings) |
|:---|:---|:---|
| **Code Reuse** | ✅ 100% | ❌ Needs refactor |
| **Performance** | ~2ms latency | <1ms latency |
| **Debugging** | ✅ Easy (HTTP logs) | ❌ Harder (Rust+Python) |
| **Maturity** | ✅ Proven (2025) | ⚠️ New (2025) |
| **Complexity** | Low-Medium | Medium-High |
| **Learning Curve** | Low (FastAPI) | High (Rust + Pyo3) |
| **Production Ready** | ✅ Yes | ⚠️ Experimental |
| **Recommended For** | Existing codebases | Greenfield projects |

**Winner: Sidecar** - Maximize code reuse, minimize risk

---

## Why NOT Rewrites?

**User asked about rewriting.** Here's why we DON'T need to:

1. **Existing engine is solid:**
   - ✅ Phase 1 context engineering (900+ lines, production-ready)
   - ✅ Multi-provider support (Ollama, Claude, GPT, DeepSeek, Gemini)
   - ✅ Fallback chains, error handling
   - ✅ SOLID principles, well-tested

2. **Sidecar pattern enables 100% reuse:**
   - FastAPI is just a thin HTTP wrapper
   - ~200 lines of routing code
   - Rest is existing Emiliano logic

3. **Cost of rewrite:**
   - 2-3 weeks of dev time wasted
   - New bugs introduced
   - Lose existing features
   - Delay desktop app launch

4. **Better to iterate:**
   - Ship desktop app in 4-6 weeks
   - Get user feedback
   - Improve backend based on real usage

**Verdict:** No rewrites needed. Sidecar pattern is the right choice.

---

## Next Steps

### Immediate (This Session)
1. ✅ Complete Phase 1 context integration (remaining: CLI commands)
2. ✅ Research desktop UI state-of-the-art
3. ✅ Design architecture
4. 🔨 Create FastAPI backend wrapper

### Short-Term (Next 1-2 Weeks)
1. Implement FastAPI routes + WebSocket streaming
2. Setup Tauri project + sidecar configuration
3. Build React frontend foundation

### Medium-Term (Weeks 3-6)
1. Full integration
2. Cross-platform testing
3. Polish & release

---

## Key Documents

1. **`docs/desktop-ui-architecture.md`** - Full technical architecture (this doc)
2. **`docs/context-engineering-sota-analysis.md`** - Context management roadmap
3. **`docs/phase1-implementation-summary.md`** - Phase 1 context features

---

**Recommendation:** Proceed with Tauri 2.0 + React + Python FastAPI Sidecar architecture.

**No rewrites needed.** Existing Emiliano engine is production-ready and will be 100% reused.

**Timeline:** 4-6 weeks to MVP, fully local, cross-platform desktop app.

---

**Document Version:** 1.0
**Created:** 2026-11-02
**Status:** Ready for implementation
