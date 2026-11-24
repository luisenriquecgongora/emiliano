/**
 * Emiliano Deep Concept & Code Inspector Overlay (Shadow DOM)
 * Provides an in-page floating glass HUD for instant technical deconstruction,
 * canonical specifications, and replication discovery without leaving the reading flow.
 */

(function () {
  const ENGINE_API_URL = "http://127.0.0.1:8765/api/cowork/research";

  function renderSimpleMarkdown(md) {
    if (!md) return "";
    let html = md
      // Escaping HTML characters
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      // Fenced code blocks
      .replace(/```([\w-]*)\n([\s\S]*?)```/g, function (_, lang, code) {
        return `<pre><code class="lang-${lang}">${code.trim()}</code></pre>`;
      })
      // Inline code
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      // Headings
      .replace(/^#### (.*$)/gim, "<h4>$1</h4>")
      .replace(/^### (.*$)/gim, "<h3>$1</h3>")
      .replace(/^## (.*$)/gim, "<h2>$1</h2>")
      .replace(/^# (.*$)/gim, "<h1>$1</h1>")
      // Bold & Italic
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      // Links with target="_blank"
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1 ↗</a>')
      // Bullet lists
      .replace(/^\s*[-*]\s+(.*$)/gim, "<li>$1</li>")
      .replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>")
      // Paragraphs
      .replace(/\n\n+/g, "</p><p>")
      .replace(/\n/g, "<br>");

    // Fix nested <ul>
    html = html.replace(/<\/ul>\s*<ul>/g, "");
    return `<div class="hud-markdown"><p>${html}</p></div>`;
  }

  function getSurroundingContext(selection) {
    if (!selection || selection.rangeCount === 0) return "";
    try {
      const range = selection.getRangeAt(0);
      const container = range.commonAncestorContainer;
      const el = container.nodeType === Node.ELEMENT_NODE ? container : container.parentElement;
      return (el ? el.innerText || el.textContent || "" : "").slice(0, 1000);
    } catch (_) {
      return "";
    }
  }

  function detectLanguage(selection) {
    if (!selection || selection.rangeCount === 0) return "";
    try {
      const range = selection.getRangeAt(0);
      let el = range.commonAncestorContainer;
      if (el.nodeType !== Node.ELEMENT_NODE) el = el.parentElement;

      while (el && el !== document.body) {
        const cls = el.className || "";
        const langMatch = String(cls).match(/lang(?:uage)?-([\w-]+)/i);
        if (langMatch) return langMatch[1];
        if (el.getAttribute("data-lang")) return el.getAttribute("data-lang");
        el = el.parentElement;
      }
    } catch (_) {}
    return "";
  }

  window.__openEmilianoInspector = function (targetText, queryType = "concept") {
    const selection = window.getSelection();
    const selText = targetText || (selection ? selection.toString().trim() : "");
    if (!selText) return;

    const surroundingContext = getSurroundingContext(selection);
    const detectedLang = detectLanguage(selection);

    let host = document.getElementById("emiliano-inspector-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "emiliano-inspector-host";
      document.documentElement.appendChild(host);
    }

    let shadow = host.shadowRoot;
    if (!shadow) {
      shadow = host.attachShadow({ mode: "open" });
    }

    const badgeLabel = queryType === "replications" ? "Replications" : (queryType === "explain-code" ? "Code Logic" : "Concept");

    shadow.innerHTML = `
      <style>
        :host {
          all: initial;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
          color-scheme: dark;
          font-size: 13px;
          line-height: 1.5;
          color: #f1f5f9;
          z-index: 2147483647;
          position: fixed;
          pointer-events: none;
        }
        *, *::before, *::after { box-sizing: border-box; }
        .hud-panel {
          pointer-events: auto;
          position: fixed;
          bottom: 24px;
          right: 24px;
          width: 490px;
          max-width: calc(100vw - 48px);
          max-height: calc(100vh - 48px);
          display: flex;
          flex-direction: column;
          background: rgba(15, 23, 42, 0.95);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border: 1px solid rgba(99, 102, 241, 0.35);
          border-radius: 16px;
          box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8), 0 0 30px rgba(99, 102, 241, 0.2);
          overflow: hidden;
          animation: hud-in 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        @keyframes hud-in {
          from { opacity: 0; transform: translateY(16px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
        .hud-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          background: rgba(30, 41, 59, 0.7);
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);
          cursor: grab;
          user-select: none;
        }
        .hud-header:active { cursor: grabbing; }
        .hud-branding { display: flex; align-items: center; gap: 8px; }
        .hud-logo {
          width: 24px;
          height: 24px;
          background: linear-gradient(135deg, #6366f1, #10b981);
          color: #fff;
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
          font-size: 13px;
        }
        .hud-title { font-weight: 600; font-size: 13px; color: #f8fafc; }
        .hud-badge {
          padding: 2px 7px;
          border-radius: 10px;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
          background: rgba(99, 102, 241, 0.2);
          color: #818cf8;
          border: 1px solid rgba(99, 102, 241, 0.3);
          margin-left: 6px;
        }
        .hud-icon-btn {
          background: transparent;
          border: none;
          color: #94a3b8;
          width: 26px;
          height: 26px;
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          font-size: 14px;
        }
        .hud-icon-btn:hover { background: rgba(255, 255, 255, 0.1); color: #fff; }
        .hud-snippet {
          margin: 10px 16px 0;
          padding: 8px 12px;
          background: rgba(15, 23, 42, 0.7);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 8px;
          font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
          font-size: 11.5px;
          color: #93c5fd;
          white-space: pre-wrap;
          word-break: break-all;
          max-height: 55px;
          overflow-y: auto;
        }
        .hud-body {
          padding: 14px 16px;
          overflow-y: auto;
          flex: 1;
          max-height: 420px;
        }
        .hud-body::-webkit-scrollbar { width: 5px; }
        .hud-body::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.2); border-radius: 3px; }
        .hud-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 32px 0;
          gap: 12px;
          color: #94a3b8;
          font-size: 12.5px;
        }
        .hud-spinner {
          width: 30px;
          height: 30px;
          border: 3px solid rgba(99, 102, 241, 0.2);
          border-top-color: #6366f1;
          border-radius: 50%;
          animation: hud-spin 0.8s linear infinite;
        }
        @keyframes hud-spin { to { transform: rotate(360deg); } }
        .hud-markdown h3 { font-size: 13.5px; color: #a5b4fc; margin: 14px 0 6px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); padding-bottom: 3px; }
        .hud-markdown h4 { font-size: 12.5px; color: #38bdf8; margin: 12px 0 4px; }
        .hud-markdown p { margin: 0 0 8px; color: #cbd5e1; font-size: 12.5px; line-height: 1.55; }
        .hud-markdown ul { margin: 0 0 8px; padding-left: 18px; }
        .hud-markdown li { margin-bottom: 4px; color: #cbd5e1; font-size: 12px; }
        .hud-markdown a { color: #38bdf8; text-decoration: none; border-bottom: 1px dotted rgba(56, 189, 248, 0.4); }
        .hud-markdown a:hover { color: #7dd3fc; border-bottom-style: solid; }
        .hud-markdown code { font-family: ui-monospace, Menlo, Monaco, Consolas, monospace; background: rgba(255, 255, 255, 0.08); padding: 2px 5px; border-radius: 4px; font-size: 11.5px; color: #e2e8f0; }
        .hud-markdown pre { background: #090d16; border: 1px solid rgba(255, 255, 255, 0.08); padding: 10px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
        .hud-footer {
          padding: 10px 16px 14px;
          background: rgba(30, 41, 59, 0.5);
          border-top: 1px solid rgba(255, 255, 255, 0.08);
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .hud-actions-row { display: flex; justify-content: space-between; align-items: center; }
        .hud-copy-btn {
          background: rgba(255, 255, 255, 0.07);
          border: 1px solid rgba(255, 255, 255, 0.1);
          color: #cbd5e1;
          padding: 4px 10px;
          border-radius: 6px;
          font-size: 11px;
          cursor: pointer;
        }
        .hud-copy-btn:hover { background: rgba(255, 255, 255, 0.12); color: #fff; }
        .hud-input-row { display: flex; gap: 8px; }
        .hud-input {
          flex: 1;
          background: rgba(15, 23, 42, 0.8);
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 8px;
          padding: 8px 12px;
          color: #f8fafc;
          font-size: 12px;
          outline: none;
        }
        .hud-input:focus { border-color: #6366f1; }
        .hud-submit-btn {
          background: linear-gradient(135deg, #6366f1, #4f46e5);
          border: none;
          color: #fff;
          padding: 0 14px;
          border-radius: 8px;
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
        }
      </style>
      <div class="hud-panel" id="hud-panel">
        <div class="hud-header" id="hud-drag-handle">
          <div class="hud-branding">
            <div class="hud-logo">E</div>
            <span class="hud-title">Emiliano Technical Inspector</span>
            <span class="hud-badge">${badgeLabel}</span>
          </div>
          <div class="hud-header-actions">
            <button class="hud-icon-btn" id="btn-close" title="Close (Esc)">✕</button>
          </div>
        </div>
        <div class="hud-snippet">${selText.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>
        <div class="hud-body" id="hud-body">
          <div class="hud-loading">
            <div class="hud-spinner"></div>
            <span>Analyzing concept & discovering canonical replications...</span>
          </div>
        </div>
        <div class="hud-footer">
          <div class="hud-actions-row">
            <button class="hud-copy-btn" id="btn-copy">📋 Copy Analysis</button>
            <span style="font-size: 10px; color: #64748b;">Esc to close &bull; Drag to move</span>
          </div>
          <div class="hud-input-row">
            <input type="text" class="hud-input" id="hud-followup-input" placeholder="Ask follow-up question about this concept...">
            <button class="hud-submit-btn" id="btn-submit">Ask</button>
          </div>
        </div>
      </div>
    `;

    const panel = shadow.getElementById("hud-panel");
    const body = shadow.getElementById("hud-body");
    const btnClose = shadow.getElementById("btn-close");
    const btnCopy = shadow.getElementById("btn-copy");
    const btnSubmit = shadow.getElementById("btn-submit");
    const inputFollowup = shadow.getElementById("hud-followup-input");
    const dragHandle = shadow.getElementById("hud-drag-handle");

    let currentMarkdown = "";
    const conversationHistory = [];

    // Close logic
    function closeHUD() {
      if (host && host.parentNode) {
        host.parentNode.removeChild(host);
      }
      document.removeEventListener("keydown", onKeyDown);
    }

    function onKeyDown(e) {
      if (e.key === "Escape") closeHUD();
    }
    document.addEventListener("keydown", onKeyDown);
    btnClose.addEventListener("click", closeHUD);

    // Draggable header logic
    let isDragging = false;
    let startX = 0, startY = 0, initialLeft = 0, initialTop = 0;

    dragHandle.addEventListener("mousedown", (e) => {
      isDragging = true;
      const rect = panel.getBoundingClientRect();
      startX = e.clientX;
      startY = e.clientY;
      initialLeft = rect.left;
      initialTop = rect.top;
      panel.style.bottom = "auto";
      panel.style.right = "auto";
      panel.style.left = `${initialLeft}px`;
      panel.style.top = `${initialTop}px`;

      const onMouseMove = (moveEvt) => {
        if (!isDragging) return;
        const dx = moveEvt.clientX - startX;
        const dy = moveEvt.clientY - startY;
        panel.style.left = `${Math.max(10, Math.min(window.innerWidth - rect.width - 10, initialLeft + dx))}px`;
        panel.style.top = `${Math.max(10, Math.min(window.innerHeight - rect.height - 10, initialTop + dy))}px`;
      };

      const onMouseUp = () => {
        isDragging = false;
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    });

    // Copy to clipboard
    btnCopy.addEventListener("click", () => {
      if (currentMarkdown) {
        navigator.clipboard.writeText(currentMarkdown);
        btnCopy.textContent = "✓ Copied!";
        setTimeout(() => { btnCopy.textContent = "📋 Copy Analysis"; }, 2000);
      }
    });

    // Research API Call
    async function executeQuery(followUpQuestion = null) {
      if (followUpQuestion) {
        body.innerHTML += `
          <div style="margin-top: 14px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08);">
            <div style="font-weight: 600; color: #818cf8; margin-bottom: 6px;">Q: ${followUpQuestion.replace(/</g, "&lt;")}</div>
            <div class="hud-loading" style="padding: 12px 0;">
              <div class="hud-spinner" style="width:20px;height:20px;"></div>
              <span>Formulating response...</span>
            </div>
          </div>
        `;
        body.scrollTop = body.scrollHeight;
      }

      try {
        const payload = {
          selection: selText,
          context: surroundingContext,
          url: window.location.href,
          page_title: document.title,
          language: detectedLang,
          query_type: queryType,
          follow_up: followUpQuestion,
          history: conversationHistory
        };

        const res = await fetch(ENGINE_API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          throw new Error(`Engine returned HTTP ${res.status}`);
        }

        const data = await res.json();
        currentMarkdown = data.markdown || "";

        if (followUpQuestion) {
          // Remove the temporary mini-loading indicator
          const lastLoading = body.querySelector(".hud-loading");
          if (lastLoading) lastLoading.remove();
          body.innerHTML += renderSimpleMarkdown(currentMarkdown);
          conversationHistory.push({ role: "user", content: followUpQuestion });
          conversationHistory.push({ role: "assistant", content: currentMarkdown });
        } else {
          body.innerHTML = renderSimpleMarkdown(currentMarkdown);
          conversationHistory.push({ role: "assistant", content: currentMarkdown });
        }
        body.scrollTop = body.scrollHeight;
      } catch (err) {
        console.warn("[Emiliano Inspector] Error contacting engine:", err);
        body.innerHTML = `
          <div style="padding: 16px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px;">
            <div style="font-weight: 600; color: #f87171; margin-bottom: 6px;">Cannot Connect to Emiliano Engine</div>
            <p style="font-size: 12px; color: #cbd5e1; margin-bottom: 10px;">
              Make sure the Emiliano Desktop Daemon is running on <code>127.0.0.1:8765</code>.
            </p>
            <div style="font-size: 11px; color: #94a3b8;">
              Quick Links: <a href="https://github.com/search?q=${encodeURIComponent(selText)}" target="_blank">Search GitHub</a> &bull;
              <a href="https://developer.mozilla.org/en-US/search?q=${encodeURIComponent(selText)}" target="_blank">Search MDN</a>
            </div>
          </div>
        `;
      }
    }

    // Trigger initial query
    executeQuery();

    // Submit follow-up
    function submitFollowup() {
      const q = inputFollowup.value.trim();
      if (!q) return;
      inputFollowup.value = "";
      executeQuery(q);
    }

    btnSubmit.addEventListener("click", submitFollowup);
    inputFollowup.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submitFollowup();
      }
    });
  };

  // Listen for messages from background script
  if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
    chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
      if (msg.type === "EMILIANO_INSPECT_TARGET") {
        window.__openEmilianoInspector(msg.selection, msg.queryType);
        sendResponse({ opened: true });
        return true;
      }
    });
  }
})();
