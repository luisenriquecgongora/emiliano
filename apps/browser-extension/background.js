/**
 * Emiliano Cowork Companion - Background Worker (Cross-Browser Chrome & Firefox)
 * Manages WebSocket connection to Emiliano Desktop Engine (127.0.0.1:8765/ws/browser),
 * executes privileged browser automation tasks, and drives the Deep Concept & Code Inspector.
 */

// Cross-browser WebExtensions API normalization
const extApi = (typeof browser !== "undefined" && browser.runtime) ? browser : chrome;
const actionApi = extApi.action || extApi.browserAction || (typeof chrome !== "undefined" ? chrome.action : null);

const DEFAULT_SERVER_URL = "ws://127.0.0.1:8765/ws/browser";
let socket = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let isConnecting = false;
const attachedDebuggers = new Set();

// Detect browser environment
const isFirefox = navigator.userAgent.toLowerCase().includes("firefox");
const browserName = isFirefox ? "firefox" : "chrome";

function setBadge(text, color) {
  try {
    if (actionApi && actionApi.setBadgeText) {
      actionApi.setBadgeText({ text });
      if (color && actionApi.setBadgeBackgroundColor) {
        actionApi.setBadgeBackgroundColor({ color });
      }
    }
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// WebSocket Lifecycle, Heartbeat & Auto-Reconnect
// ---------------------------------------------------------------------------

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({ type: "PING", timestamp: Date.now() }));
        if (extApi.runtime && extApi.runtime.getPlatformInfo) {
          extApi.runtime.getPlatformInfo(() => {});
        }
      } catch (err) {
        console.warn("[Emiliano Bridge] Heartbeat ping failed:", err);
      }
    }
  }, 15000);
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
    console.log(`[Emiliano Bridge] Connected to Emiliano Engine (${browserName}).`);
    setBadge("ON", "#10b981");

    startHeartbeat();

    // Handshake with client browser metadata
    socket.send(JSON.stringify({
      type: "EXTENSION_HANDSHAKE",
      payload: {
        version: extApi.runtime.getManifest().version,
        name: extApi.runtime.getManifest().name,
        browser: browserName,
        userAgent: navigator.userAgent
      }
    }));
  };

  socket.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "PONG") {
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
    setBadge("OFF", "#ef4444");
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

// Keep-alive alarm
if (extApi.alarms) {
  try {
    extApi.alarms.create("emiliano-keep-alive", { periodInMinutes: 0.5 });
    extApi.alarms.onAlarm.addListener((alarm) => {
      if (alarm.name === "emiliano-keep-alive" || alarm.name === "keepAlive") {
        if (!socket || socket.readyState !== WebSocket.OPEN) {
          console.log("[Emiliano Bridge] Alarm keep-alive reconnecting to engine...");
          connect();
        } else {
          try {
            socket.send(JSON.stringify({ type: "PING", timestamp: Date.now() }));
            if (extApi.runtime && extApi.runtime.getPlatformInfo) {
              extApi.runtime.getPlatformInfo(() => {});
            }
          } catch (e) {
            connect();
          }
        }
      }
    });
  } catch (_) {}
}

extApi.runtime.onStartup.addListener(() => {
  console.log("[Emiliano Bridge] Browser startup detected. Connecting...");
  connect();
  setupContextMenus();
});

extApi.runtime.onInstalled.addListener(() => {
  console.log("[Emiliano Bridge] Extension installed or updated. Connecting...");
  connect();
  setupContextMenus();
});

// ---------------------------------------------------------------------------
// Right-Click Context Menu for Concept & Code Deep Research
// ---------------------------------------------------------------------------

function setupContextMenus() {
  if (!extApi.contextMenus) return;
  try {
    extApi.contextMenus.removeAll(() => {
      extApi.contextMenus.create({
        id: "emiliano-inspect-concept",
        title: "🔍 Inspect Concept with Emiliano",
        contexts: ["selection"]
      });
      extApi.contextMenus.create({
        id: "emiliano-find-replications",
        title: "🧬 Find Deep Links & Replications",
        contexts: ["selection"]
      });
      extApi.contextMenus.create({
        id: "emiliano-explain-code",
        title: "⚡ Explain Code & Architecture",
        contexts: ["selection"]
      });
    });
  } catch (err) {
    console.warn("[Emiliano Bridge] Context menu registration failed:", err);
  }
}

if (extApi.contextMenus && extApi.contextMenus.onClicked) {
  extApi.contextMenus.onClicked.addListener(async (info, tab) => {
    if (!tab || !tab.id || !info.selectionText) return;
    const queryType = (info.menuItemId || "").replace("emiliano-", "");

    try {
      // Injects the in-page Shadow DOM inspector overlay
      await extApi.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["hud_overlay.js"]
      });

      // Triggers inspection with captured selection
      await extApi.tabs.sendMessage(tab.id, {
        type: "EMILIANO_INSPECT_TARGET",
        selection: info.selectionText,
        queryType: queryType
      });
    } catch (err) {
      console.warn("[Emiliano Inspector] Failed to inject inspector into tab:", err);
    }
  });
}

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
        setTimeout(() => extApi.runtime.reload(), 100);
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
  const tabs = await extApi.tabs.query({});
  if (targetUrlMatch) {
    const match = tabs.find(t => (t.url || "").toLowerCase().includes(targetUrlMatch.toLowerCase()));
    if (match) return match;
  }
  const active = tabs.find(t => t.active);
  return active || tabs[0] || null;
}

async function getTabs(query = {}) {
  const tabs = await extApi.tabs.query(query);
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
    await extApi.tabs.update(tab.id, { url, active: !background });
    return { tabId: tab.id, url, navigated: true };
  } else {
    tab = await extApi.tabs.create({ url, active: !background });
    return { tabId: tab.id, url, created: true };
  }
}

// ---------------------------------------------------------------------------
// DOM Scripting & Virtual Interaction
// ---------------------------------------------------------------------------

async function executeScript(params) {
  const tab = await resolveTab(params.targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  // If CDP available (Chrome), try Runtime.evaluate
  if (extApi.debugger) {
    try {
      await ensureDebuggerAttached(tab.id);
      const evalRes = await extApi.debugger.sendCommand({ tabId: tab.id }, "Runtime.evaluate", {
        expression: params.code,
        returnByValue: true,
        awaitPromise: true,
      });
      if (evalRes) {
        if (evalRes.exceptionDetails) {
          return { __error: evalRes.exceptionDetails.text || "Runtime evaluation error" };
        }
        if (evalRes.result) {
          if (evalRes.result.type === "undefined") return undefined;
          return evalRes.result.value;
        }
      }
    } catch (_) {}
  }

  // Cross-browser scripting.executeScript fallback
  const [res] = await extApi.scripting.executeScript({
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

  const [res] = await extApi.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    func: async (sel, val) => {
      const start = Date.now();
      let el = null;
      while (Date.now() - start < 8000) {
        el = document.querySelector(sel);
        if (el) break;
        await new Promise(r => setTimeout(r, 300));
      }
      if (!el) return false;

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

  const [res] = await extApi.scripting.executeScript({
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

  const [res] = await extApi.scripting.executeScript({
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
          if (rect.x < 150) return false;
        } catch (_) {}
        const txt = el.innerText || el.textContent || '';
        return txt.trim().toLowerCase().includes(q);
      });

      if (matches.length === 0) return false;

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
  if (!extApi.debugger) return;
  if (attachedDebuggers.has(tabId)) return;
  try {
    await extApi.debugger.attach({ tabId }, "1.3");
    attachedDebuggers.add(tabId);
    await extApi.debugger.sendCommand({ tabId }, "Page.enable", {});
    await extApi.debugger.sendCommand({ tabId }, "Runtime.enable", {});
  } catch (_) {}
}

async function sendCdpCommand(params) {
  if (!extApi.debugger) throw new Error("CDP debugger API is only supported on Chromium browsers.");
  const { method, params: cdpParams = {}, targetUrlMatch } = params;
  const tab = await resolveTab(targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  await ensureDebuggerAttached(tab.id);
  return await extApi.debugger.sendCommand({ tabId: tab.id }, method, cdpParams);
}

async function captureScreenshot(params) {
  const tab = await resolveTab(params.targetUrlMatch);
  if (!tab) throw new Error("No matching browser tab found.");

  // If debugger available (Chrome), try Page.captureScreenshot
  if (extApi.debugger) {
    try {
      await ensureDebuggerAttached(tab.id);
      const result = await extApi.debugger.sendCommand({ tabId: tab.id }, "Page.captureScreenshot", {
        format: "png",
        fromSurface: true
      });
      if (result && result.data) {
        return "data:image/png;base64," + result.data;
      }
    } catch (_) {}
  }

  // Cross-browser fallback
  return await extApi.tabs.captureVisibleTab(tab.windowId, { format: "png" });
}

function detachAllDebuggers() {
  if (!extApi.debugger) return;
  for (const tabId of attachedDebuggers) {
    try {
      extApi.debugger.detach({ tabId });
    } catch (_) {}
  }
  attachedDebuggers.clear();
}

if (extApi.debugger && extApi.debugger.onDetach) {
  extApi.debugger.onDetach.addListener((source) => {
    if (source.tabId) attachedDebuggers.delete(source.tabId);
  });
}

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

  setBadge("REC", "#ef4444");

  try {
    await extApi.scripting.executeScript({
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

  setBadge("ON", "#10b981");

  return {
    status: "recording_stopped",
    goal: goal,
    events_count: events.length,
    events: events
  };
}

extApi.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "RECORDED_EVENT" && recordingSession.active) {
    recordingSession.events.push(msg.event);
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

// Setup context menus and connect on startup
setupContextMenus();
connect();
