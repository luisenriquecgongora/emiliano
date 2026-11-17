# 0006. In-Browser Companion Extension Architecture for Silent Cowork Automation

- **Status:** Accepted (2026-11-17)
- **Date:** 2026-11-17
- **Target Systems:** Emiliano Engine Daemon, Browser Companion Extension (`@emiliano/browser-extension`), Desktop Cowork Harness

---

## 1. Context

Emiliano's Desktop Cowork platform enables autonomous agents to perform complex multi-step workflows alongside human operators. In web-based tasks (e.g. B2B prospecting, social outreach on Instagram/LinkedIn, internal portal data entry), the engine originally relied on two paradigms:

1. **OS-Level Win32 Automation (`pyautogui`, UIA, `user32.dll`):**
   * *Problem:* Emulates a physical user. Moving the mouse cursor interrupts the operator's manual typing and pointing. Bringing windows to the top (`SetForegroundWindow` / `WM_ACTIVATE`) steals active keyboard focus away from IDEs, terminals, or word processors.
2. **External Chrome DevTools Protocol (`--remote-debugging-port=9222`):**
   * *Problem:* Enables virtual input without moving the mouse, but requires the user to launch Chrome with custom command-line flags. If Chrome is already running under its standard profile, Chromium rejects the debugging flag unless the user terminates all open browser instances.

We needed a solution that provides **100% background, non-activating execution with zero cursor movement**, requires **zero browser restarts**, and maintains **seamless session continuity** with the user's existing logged-in accounts.

---

## 2. Decision

We implement a dedicated, open-source **Chrome Companion Extension (`@emiliano/browser-extension`)** using Manifest V3, communicating with the local engine daemon via a secure WebSocket bridge (`/ws/browser` on port 8765).

### 2.1 Internal Chromium Privileges
By operating inside Chrome's native extension runtime, the extension accesses privileged internal Chromium subsystems:
* **`chrome.debugger` API:** Enables attaching to any tab's Chrome DevTools Protocol (CDP) session internally. The engine can issue virtual keystrokes (`Input.dispatchKeyEvent`) and mouse events without needing `--remote-debugging-port` flags on the browser executable.
* **`chrome.scripting` API:** Injects React-compatible input routines directly into the DOM (e.g. `document.execCommand('insertText')` for Lexical and Draft.js rich-text editors) so state synchronization occurs without requiring window focus.
* **`chrome.tabs` API:** Manages background tabs, handles silent navigation, and captures off-screen GPU screenshots (`captureVisibleTab`).

### 2.2 Localhost WebSocket RPC Bridge
* **Endpoint:** The engine daemon exposes `ws://127.0.0.1:8765/ws/browser`.
* **Security:** `emiliano.server.security.is_origin_allowed` is updated to validate `chrome-extension://` origins while strictly rejecting untrusted web origins.
* **Protocol:** Lightweight JSON-RPC with request IDs (`uuid4`), supporting commands: `navigate`, `type_into`, `click_element`, `click_by_text`, `capture_screenshot`, `cdp_command`, and `get_tabs`.

### 2.3 Cascading Cowork Fallback Hierarchy
The campaign and cowork engines implement a 3-tier execution cascade:
1. **Tier 1 (Preferred): Browser Extension Mode.** If the extension is loaded and connected, all operations route through the extension. Mouse and window focus are completely untouched.
2. **Tier 2: Remote CDP Mode.** If the extension is offline but Chrome is listening on port 9222, commands route via `ChromeDevToolsClient`.
3. **Tier 3 (Fallback): Foreground OS Cowork Mode.** If neither is available, the engine uses pinned window geometry, UIA element detection, and Win32 synthetic inputs.

---

## 3. Consequences & Tradeoffs

### Positive Consequences
* **Zero Focus Hijacking:** Operators can write code, participate in video calls, or browse without mouse jitter or lost keystrokes.
* **Zero Authentication Friction:** The extension operates within the user's primary Chrome profile, inheriting active cookies and login sessions (e.g., `@plaatoos` on Instagram).
* **High Anti-Bot Trust Score:** Requests execute in a standard, authentic Chrome browser instance with genuine WebGL, canvas, and extension environments—eliminating headless detection heuristics.
* **No Web Store Publishing Required:** Distributed directly in the open-source repository as an unpacked extension loaded in developer mode in 15 seconds.

### Tradeoffs & Mitigations
* **Requires Chromium-Based Browser:** The extension runs on Google Chrome, Microsoft Edge, Brave, and Opera. (Mitigation: Tier 3 OS fallback remains fully functional for non-Chromium apps).
* **Initial One-Time Load:** The operator must click "Load unpacked" once in `chrome://extensions`. (Mitigation: Documented with 15-second setup instructions and visual badge indicators).
