/**
 * Emiliano Cowork Companion - Background Service Worker
 * Manages WebSocket connection to Emiliano Desktop Engine (127.0.0.1:8765/ws/browser)
 * and executes privileged browser automation tasks (DOM manipulation, virtual input, navigation).
 */

const DEFAULT_SERVER_URL = "ws://127.0.0.1:8765/ws/browser";
let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let isConnecting = false;
const attachedDebuggers = new Set();

// ---------------------------------------------------------------------------
// WebSocket Lifecycle, Heartbeat & Auto-Reconnect
// ---------------------------------------------------------------------------

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({ type: "PING", timestamp: Date.now() }));
        // Calling a lightweight Chrome API resets the MV3 30-second idle shutdown timer
        chrome.runtime.getPlatformInfo(() => {});
      } catch (err) {
        console.warn("[Emiliano Bridge] Heartbeat ping failed:", err);
      }
    }
  }, 15000); // Send ping every 15 seconds
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  isConnecting = true;
  console.log(`[Emiliano Bridge] Connecting to ${DEFAULT_SERVER_URL}...`);

  try {
    socket = new WebSocket(DEFAULT_SERVER_URL);
  } catch (err) {
    console.warn("[Emiliano Bridge] Failed to instantiate WebSocket:", err);
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    isConnecting = false;
    console.log("[Emiliano Bridge] Connected to Emiliano Engine.");
    chrome.action.setBadgeText({ text: "ON" });
    chrome.action.setBadgeBackgroundColor({ color: "#10b981" }); // Emerald green

    // Start periodic keepalive heartbeat
    startHeartbeat();

    // Handshake
    socket.send(JSON.stringify({
      type: "EXTENSION_HANDSHAKE",
      payload: {
        version: chrome.runtime.getManifest().version,
        name: chrome.runtime.getManifest().name,
        userAgent: navigator.userAgent
      }
    }));
  };

  socket.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "PONG") {
        // Heartbeat ACK from server
        return;
      }
      if (msg.action) {
        await handleCommand(msg);
      }
    } catch (err) {
      console.error("[Emiliano Bridge] Error processing message:", err, event.data);
    }
  };

  socket.onclose = (event) => {
    isConnecting = false;
    socket = null;
    stopHeartbeat();
    console.warn(`[Emiliano Bridge] Disconnected (code: ${event.code}). Retrying...`);
    chrome.action.setBadgeText({ text: "OFF" });
    chrome.action.setBadgeBackgroundColor({ color: "#ef4444" }); // Red
    detachAllDebuggers();
    scheduleReconnect();
  };

  socket.onerror = (err) => {
    console.error("[Emiliano Bridge] WebSocket error:", err);
    stopHeartbeat();
    if (socket) socket.close();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    connect();
  }, 3000);
}

// Keep service worker alive and reconnect even if Chrome suspends the thread
chrome.alarms.create("emiliano-keep-alive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "emiliano-keep-alive") {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      console.log("[Emiliano Bridge] Alarm keep-alive reconnecting to engine...");
      connect();
    } else {
      try {
        socket.send(JSON.stringify({ type: "PING", timestamp: Date.now() }));
        chrome.runtime.getPlatformInfo(() => {});
      } catch (e) {
        connect();
      }
    }
  }
});

chrome.runtime.onStartup.addListener(() => {
  console.log("[Emiliano Bridge] Browser startup detected. Connecting...");
  connect();
});

chrome.runtime.onInstalled.addListener(() => {
  console.log("[Emiliano Bridge] Extension installed or updated. Connecting...");
  connect();
});

// ---------------------------------------------------------------------------
// Command Dispatcher
// ---------------------------------------------------------------------------

async function handleCommand(msg) {
  const { id, action, params = {} } = msg;
  try {
    let result = null;
    switch (action) {
      case "get_tabs":
        result = await getTabs(params.query);
        break;
      case "navigate":
        result = await navigateTab(params);
        break;
      case "execute_script":
        result = await executeScript(params);
        break;
      case "type_into":
        result = await typeInto(params);
        break;
      case "click_element":
        result = await clickElement(params);
        break;
      case "click_by_text":
        result = await clickByText(params);
        break;
      case "capture_screenshot":
        result = await captureScreenshot(params);
        break;
      case "cdp_command":
        result = await sendCdpCommand(params);
        break;
      case "start_recording":
        result = await startRecording(params);
        break;
      case "stop_recording":
        result = await stopRecording(params);
        break;
      case "reload_extension":
        sendReply({ id, result: { status: "reloading" }, status: "ok" });
        setTimeout(() => chrome.runtime.reload(), 100);
        return;
      default:
        throw new Error(`Unknown action: ${action}`);
    }

    sendReply({ id, result, status: "ok" });
  } catch (err) {
    console.error(`[Emiliano Bridge] Command '${action}' failed:`, err);
    sendReply({ id, error: err.message || String(err), status: "error" });
  }
}

function sendReply(payload) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

// ---------------------------------------------------------------------------
// Tab Resolution Utilities
// ---------------------------------------------------------------------------

async function resolveTab(targetUrlMatch) {
  const tabs = await chrome.tabs.query({});
  if (targetUrlMatch) {
    const match = tabs.find(t => (t.url || "").toLowerCase().includes(targetUrlMatch.toLowerCase()));
    if (match) return match;
  }
  // Fallback to active tab, or first tab
  const active = tabs.find(t => t.active);
  return active || tabs[0] || null;
}

async function getTabs(query = {}) {
  const tabs = await chrome.tabs.query(query);
  return tabs.map(t => ({
    id: t.id,
    url: t.url,
    title: t.title,
    active: t.active,
    status: t.status,
    windowId: t.windowId
  }));
}

async function navigateTab(params) {
  const { url, targetUrlMatch, background = true } = params;
  let tab = await resolveTab(targetUrlMatch);

  if (tab) {
    await chrome.tabs.update(tab.id, { url, active: !background });
    return { tabId: tab.id, url, navigated: true };
  } else {
    tab = await chrome.tabs.create({ url, active: !background });
    return { tabId: tab.id, url, created: true };
  }
}

// ---------------------------------------------------------------------------
// DOM Scripting & Virtual Interaction
// ---------------------------------------------------------------------------

async function executeScript(params) {
  const tab = await resolveTab(params.targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  // Prefer CDP Runtime.evaluate: bypasses page Content Security Policy (CSP) and unsafe-eval restrictions
  try {
    await ensureDebuggerAttached(tab.id);
    const evalRes = await chrome.debugger.sendCommand({ tabId: tab.id }, "Runtime.evaluate", {
      expression: params.code,
      returnByValue: true,
      awaitPromise: true,
    });
    if (evalRes) {
      if (evalRes.exceptionDetails) {
        console.warn("[Emiliano Bridge] Runtime.evaluate exception:", evalRes.exceptionDetails);
        return { __error: evalRes.exceptionDetails.text || "Runtime evaluation error" };
      }
      if (evalRes.result) {
        if (evalRes.result.type === "undefined") return undefined;
        return evalRes.result.value;
      }
    }
  } catch (cdpErr) {
    console.warn("[Emiliano Bridge] CDP Runtime.evaluate failed, falling back to scripting:", cdpErr);
  }

  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "ISOLATED",
    func: (codeStr) => {
      try {
        const fn = new Function("return (" + codeStr + ")");
        return fn();
      } catch (e1) {
        try {
          const fn2 = new Function(codeStr);
          return fn2();
        } catch (e2) {
          return { __error: e2.message };
        }
      }
    },
    args: [params.code]
  });
  return res ? res.result : null;
}

async function typeInto(params) {
  const { selector, text, targetUrlMatch } = params;
  const tab = await resolveTab(targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    func: async (sel, val) => {
      // Poll for up to 8s for composer to exist
      const start = Date.now();
      let el = null;
      while (Date.now() - start < 8000) {
        el = document.querySelector(sel);
        if (el) break;
        await new Promise(r => setTimeout(r, 300));
      }
      if (!el) return false;

      // Visual telemetry glow
      try {
        el.style.transition = 'all 0.25s ease';
        el.style.outline = '3px solid #6366f1';
        el.style.boxShadow = '0 0 16px rgba(99, 102, 241, 0.85)';
        setTimeout(() => {
          el.style.outline = '';
          el.style.boxShadow = '';
        }, 2000);
      } catch (_) {}

      el.focus();
      if ('value' in el && el.tagName !== 'DIV') {
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        // React Lexical / Draft.js contenteditable support
        document.execCommand('insertText', false, val);
      }
      return true;
    },
    args: [selector, text]
  });
  return res ? res.result : false;
}

async function clickElement(params) {
  const { selector, targetUrlMatch } = params;
  const tab = await resolveTab(targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    func: async (sel) => {
      const start = Date.now();
      let el = null;
      while (Date.now() - start < 6000) {
        el = document.querySelector(sel);
        if (el) break;
        await new Promise(r => setTimeout(r, 300));
      }
      if (!el) return false;

      // Visual telemetry glow
      try {
        el.style.transition = 'all 0.25s ease';
        el.style.outline = '3px solid #10b981';
        el.style.boxShadow = '0 0 16px rgba(16, 185, 129, 0.85)';
        setTimeout(() => {
          el.style.outline = '';
          el.style.boxShadow = '';
        }, 1500);
      } catch (_) {}

      el.scrollIntoView({ behavior: 'instant', block: 'center' });
      el.click();
      return true;
    },
    args: [selector]
  });
  return res ? res.result : false;
}

async function clickByText(params) {
  const { text, tag = "*", targetUrlMatch } = params;
  const tab = await resolveTab(targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    func: (searchStr, tagFilter) => {
      const q = searchStr.trim().toLowerCase();
      const all = Array.from(document.querySelectorAll(tagFilter || '*'));
      const matches = all.filter(el => {
        if (['HTML', 'BODY', 'SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName)) return false;
        if (el.closest('nav, [role="navigation"]')) return false;
        try {
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) return false;
          // In desktop layout, Instagram left sidebar is at x < 150
          if (rect.x < 150) return false;
        } catch (_) {}
        const txt = el.innerText || el.textContent || '';
        return txt.trim().toLowerCase().includes(q);
      });

      if (matches.length === 0) return false;

      // Pick the leaf-most element by shortest text length
      matches.sort((a, b) => {
        const lenA = (a.innerText || a.textContent || '').trim().length;
        const lenB = (b.innerText || b.textContent || '').trim().length;
        return lenA - lenB;
      });

      const leaf = matches[0];
      const clickable = leaf.closest('button, a, div[role="button"]') || leaf;

      try {
        clickable.style.transition = 'all 0.25s ease';
        clickable.style.outline = '3px solid #10b981';
        clickable.style.boxShadow = '0 0 16px rgba(16, 185, 129, 0.85)';
        setTimeout(() => {
          clickable.style.outline = '';
          clickable.style.boxShadow = '';
        }, 1500);
      } catch (_) {}

      clickable.scrollIntoView({ behavior: 'instant', block: 'center' });
      clickable.click();
      return true;
    },
    args: [text, tag]
  });
  return res ? res.result : false;
}

// ---------------------------------------------------------------------------
// Direct Chrome DevTools Protocol (CDP) via chrome.debugger
// ---------------------------------------------------------------------------

async function ensureDebuggerAttached(tabId) {
  if (attachedDebuggers.has(tabId)) return;
  await chrome.debugger.attach({ tabId }, "1.3");
  attachedDebuggers.add(tabId);
  try {
    await chrome.debugger.sendCommand({ tabId }, "Page.enable", {});
    await chrome.debugger.sendCommand({ tabId }, "Runtime.enable", {});
  } catch (_) {}
}

async function sendCdpCommand(params) {
  const { method, params: cdpParams = {}, targetUrlMatch } = params;
  const tab = await resolveTab(targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  await ensureDebuggerAttached(tab.id);
  return await chrome.debugger.sendCommand({ tabId: tab.id }, method, cdpParams);
}

async function captureScreenshot(params) {
  const tab = await resolveTab(params.targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  try {
    await ensureDebuggerAttached(tab.id);
    const result = await chrome.debugger.sendCommand({ tabId: tab.id }, "Page.captureScreenshot", {
      format: "png",
      fromSurface: true
    });
    if (result && result.data) {
      return "data:image/png;base64," + result.data;
    }
  } catch (err) {
    console.warn("[Emiliano Bridge] CDP Page.captureScreenshot failed:", err);
  }

  return await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
}

function detachAllDebuggers() {
  for (const tabId of attachedDebuggers) {
    try {
      chrome.debugger.detach({ tabId });
    } catch (_) {}
  }
  attachedDebuggers.clear();
}

chrome.debugger.onDetach.addListener((source) => {
  if (source.tabId) attachedDebuggers.delete(source.tabId);
});

// ---------------------------------------------------------------------------
// Chrome Alarms Keep-Alive for Manifest V3 Service Worker
// ---------------------------------------------------------------------------

chrome.alarms.create("keepAlive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAlive") {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      connect();
    } else {
      socket.send(JSON.stringify({ type: "PING" }));
    }
  }
});

// ---------------------------------------------------------------------------
// Teach-a-Task Demonstration Recording State & Handlers
// ---------------------------------------------------------------------------

let recordingSession = {
  active: false,
  goal: "",
  tabId: null,
  events: []
};

async function startRecording(params = {}) {
  const tab = await resolveTab(params.target_url_match);
  if (!tab || !tab.id) throw new Error("No active tab found for recording");

  recordingSession = {
    active: true,
    goal: params.goal || "User Demonstration",
    tabId: tab.id,
    events: []
  };

  chrome.action.setBadgeText({ text: "REC" });
  chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });

  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["recorder.js"]
    });
  } catch (err) {
    console.warn("[Emiliano Recorder] Failed to inject recorder.js:", err);
  }

  return { status: "recording_started", tabId: tab.id, goal: recordingSession.goal };
}

async function stopRecording(params = {}) {
  if (!recordingSession.active) {
    return { status: "not_recording", events: [] };
  }

  const events = [...recordingSession.events];
  const goal = recordingSession.goal;
  recordingSession.active = false;
  recordingSession.events = [];

  chrome.action.setBadgeText({ text: "ON" });
  chrome.action.setBadgeBackgroundColor({ color: "#10b981" });

  return {
    status: "recording_stopped",
    goal: goal,
    events_count: events.length,
    events: events
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "RECORDED_EVENT" && recordingSession.active) {
    recordingSession.events.push(msg.event);
    console.log(`[Emiliano Recorder] Event captured (${msg.event.type}):`, msg.event);
    sendResponse({ received: true });
    return true;
  }
  if (msg.type === "GET_RECORDING_STATUS") {
    sendResponse({
      active: recordingSession.active,
      goal: recordingSession.goal,
      eventsCount: recordingSession.events.length
    });
    return true;
  }
  if (msg.type === "POPUP_START_RECORDING") {
    startRecording(msg.params).then(res => sendResponse(res));
    return true;
  }
  if (msg.type === "POPUP_STOP_RECORDING") {
    stopRecording(msg.params).then(res => sendResponse(res));
    return true;
  }
});

// Initialize connection on load
connect();
