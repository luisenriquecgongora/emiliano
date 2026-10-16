# Emiliano: Future Horizons & Architectural Evolution

> *Permanent design and engineering reference for next-generation capabilities, safety invariants, and architectural milestones for the Emiliano platform.*

---

## 1. High-Priority Engineering Upgrades

### A. Deep Windows UI Automation (COM Integration)
- **Current Pattern**: Basic foreground window rect queries with PIL screenshot fallbacks.
- **Architectural Upgrade**:
  - Direct integration with `UIAutomationCore.dll` (via `comtypes` / `pywinauto.uia_element_info`).
  - Asynchronous tree extraction with property caching (`AutomationId`, `Name`, `ControlType`, `ToggleState`, `ValuePattern`, `InvokePattern`).
  - Yields deterministic bounding boxes and control states in **<15ms with 0 LLM token cost**.

### B. Per-Monitor DPI-Aware Coordinate Normalization
- **Challenge**: Modern Windows desktops frequently run 125%, 150%, or 200% DPI scaling across multi-monitor setups, causing pixel offset drift.
- **Solution**:
  - Enforce `SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)` on all Win32 threads.
  - Normalize coordinates to standard virtual desktop space before invoking mouse/keyboard actions.

### C. Terminal Buffer Emulation (`pyte`) & Rich REPL Evolutions
- **Foundation Delivered**:
  - Full interactive terminal Coworker (`emiliano` / `emiliano chat`) powered by `prompt_toolkit`.
  - Floating dropdown autocomplete on `/` with two-tier completions (`/switch`, `/policy`), persistent shell history, intent-aware agent routing, and real-time reasoning streaming.
- **Next Evolution**:
  - Embed [`pyte`](https://github.com/selectel/pyte) into `packages/engine/emiliano/harnesses/pty_mgr.py` to maintain an accurate 2D screen character grid for interactive CLI sub-agents.
  - Multi-line code block editing with syntax highlighting and external `$EDITOR` support.

---

## 2. Safety & Ergonomics

### A. HWND Window Pinning (Zero Accidental Input)
- **Invariant**: The agent must never type or click into an unintended window.
- **Mechanism**:
  - When an objective targets an application (e.g., Chrome or VS Code), the engine binds to that specific window handle (`HWND` / Process ID).
  - Before every synthetic click or keystroke, the engine verifies that the active window matches the target `HWND`.
  - If the user switches windows or moves the mouse, the engine halts immediately and prompts via the HUD.

### B. Action Preview & "Shadow Mode"
- The transparent HUD paints a high-visibility target crosshair 400ms prior to action execution with a countdown:
  > *"Clicking [Submit Order] in 0.4s... (Press Space to Pause)"*
- Provides human supervision and instant intervention for high-stakes workflows.

---

## 3. Core Memory & Procedural Learning

### A. The Unified Blackboard (Inter-Harness Context Exchange)
- A shared SQLite and vector memory layer accessible by all harnesses.
- Enables seamless handoffs:
  - **Claude Code** refactors a backend file and posts `{"service": "auth", "port": 8081, "status": "running"}` to the Blackboard.
  - **Desktop Cowork Agent** reads the event and immediately opens the browser to test the login flow without needing user intervention.

### B. "Skill Forge": Self-Compiling Deterministic Macros
- When the agent discovers a successful visual path to accomplish a goal (e.g., *"Export monthly invoice PDF from QuickBooks"*), it records the sequence of actions.
- After verification, the Skill Forge compiles this sequence into a native Python script / accessibility macro.
- Subsequent runs execute deterministically in **<500ms with zero LLM API calls**.

---

## 4. Long-Term Horizons (2026–2027)

### Horizon 1: The "Ghost Worker" (Virtual Display Isolation)
- Run UI tasks inside a background Windows Virtual Desktop, nested RDP sandbox, or containerized desktop.
- Allows Emiliano to click, browse, and test applications completely in the background without hijacking the user's physical mouse cursor.

### Horizon 2: Closed-Loop Visual Self-Healing
- After executing an action, take an immediate visual delta capture:
  - *Did the dropdown open?*
  * *Did an unexpected modal block the screen?*
- If the visual state doesn't match expectations, automatically apply a recovery strategy (e.g. scroll down, dismiss modal, retry with keyboard navigation).

### Horizon 3: Ambient Voice & Audio Awareness
- Low-latency local speech-to-text (Whisper.cpp) and audio synthesis.
- Allows conversational voice coworking: *"Emiliano, pause for a moment while I enter my password"* or *"Go ahead and push that branch to GitHub"*.
