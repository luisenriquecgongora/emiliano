#!/usr/bin/env python3
"""
Live Desktop Cowork HUD & Real-Time Vision Overlay.
Part of the agent-standards ecosystem.

Sidecar server and live dashboard for monitoring desktop agents, PlaatoOS outreach,
and cowork execution in real time. Features a live event stream tailer, simulated/visual
targeting reticle overlay (with bounding box clicks), KPI scorecard, and human interlock (pause/resume).

Usage:
    python scripts/cowork-hud.py [--log path/to/business_logs.jsonl] [--port 8765] [--open]
"""

from __future__ import annotations

import argparse
import datetime
import html
import http.server
import json
import os
import socketserver
import sys
import threading
import time
import webbrowser
from pathlib import Path

HUD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Cowork Live HUD & Vision Overlay</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; }
    code, pre, .mono { font-family: 'JetBrains Mono', monospace; }
    .pulse-dot { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .2; } }
    .custom-scroll::-webkit-scrollbar { width: 5px; height: 5px; }
    .custom-scroll::-webkit-scrollbar-track { background: #090d16; }
    .custom-scroll::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 3px; }
    .custom-scroll::-webkit-scrollbar-thumb:hover { background: #334155; }
    .reticle-ping { animation: reticle-pulse 1.5s ease-out infinite; }
    @keyframes reticle-pulse {
      0% { transform: scale(0.9); opacity: 1; }
      100% { transform: scale(1.4); opacity: 0; }
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen antialiased selection:bg-indigo-500 selection:text-white flex flex-col">

  <!-- Top Navigation Bar -->
  <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 rounded-xl bg-gradient-to-tr from-cyan-500 via-indigo-500 to-purple-600 flex items-center justify-center font-bold text-white shadow-lg shadow-cyan-500/25">
          🎯
        </div>
        <div>
          <div class="flex items-center gap-2">
            <span class="font-bold text-base tracking-tight text-white">Cowork Vision HUD</span>
            <span id="hud-status-badge" class="text-xs font-mono px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800 text-emerald-400 flex items-center gap-1.5">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 pulse-dot"></span> LIVE SIDECAR
            </span>
          </div>
          <p class="text-xs text-slate-400 font-mono mt-0.5">Stream: <span id="hud-log-name" class="text-slate-300">business_logs.jsonl</span> &bull; Port: <span id="hud-port" class="text-slate-300">8765</span></p>
        </div>
      </div>

      <!-- Human Interlock Controls -->
      <div class="flex items-center gap-3">
        <button id="btn-interlock" onclick="toggleInterlock()" class="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs tracking-wide transition flex items-center gap-2 shadow-lg shadow-rose-600/30">
          <span id="interlock-icon">⏸</span> <span id="interlock-text">Pause Agent</span>
        </button>
        <button onclick="clearEventLogs()" class="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition text-xs border border-slate-700">
          Clear View
        </button>
      </div>
    </div>
  </header>

  <!-- Live KPI Bar -->
  <section class="max-w-7xl mx-auto px-6 pt-5 pb-3 w-full">
    <div class="grid grid-cols-2 md:grid-cols-6 gap-3">
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-3 flex flex-col">
        <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Total Actions</span>
        <span id="kpi-total" class="text-xl font-extrabold text-white mt-0.5 mono">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-3 flex flex-col">
        <span class="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">DMs Dispatched</span>
        <span id="kpi-dm" class="text-xl font-extrabold text-emerald-300 mt-0.5 mono">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-3 flex flex-col">
        <span class="text-[11px] font-semibold uppercase tracking-wider text-sky-400">Emails Sent</span>
        <span id="kpi-email" class="text-xl font-extrabold text-sky-300 mt-0.5 mono">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-3 flex flex-col">
        <span class="text-[11px] font-semibold uppercase tracking-wider text-amber-400">Warm-ups</span>
        <span id="kpi-warmup" class="text-xl font-extrabold text-amber-300 mt-0.5 mono">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-3 flex flex-col">
        <span class="text-[11px] font-semibold uppercase tracking-wider text-rose-400">Skipped Leads</span>
        <span id="kpi-skip" class="text-xl font-extrabold text-rose-300 mt-0.5 mono">0</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-xl p-3 flex flex-col">
        <span class="text-[11px] font-semibold uppercase tracking-wider text-purple-400">Inbound Replies</span>
        <span id="kpi-inbound" class="text-xl font-extrabold text-purple-300 mt-0.5 mono">0</span>
      </div>
    </div>
  </section>

  <!-- Main Viewports: Left = Live Vision & Reticle Canvas, Right = Live Stream Feed -->
  <main class="max-w-7xl mx-auto px-6 pb-12 w-full flex-1 grid grid-cols-1 lg:grid-cols-12 gap-6">

    <!-- Left: Real-Time Vision & Desktop Reticle Canvas -->
    <div class="lg:col-span-7 flex flex-col space-y-4">
      <div class="bg-slate-900/80 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-col">
        <div class="flex items-center justify-between pb-3 border-b border-slate-800">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold uppercase tracking-wider text-slate-300">Targeting & Vision Overlay</span>
            <span id="vision-mode-badge" class="text-[10px] mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-400 border border-cyan-800">UIA / DOM TRACKER</span>
          </div>
          <span id="coords-badge" class="text-xs font-mono text-slate-400">Target: x=---, y=---</span>
        </div>

        <!-- Simulated Viewport Canvas (16:9 ratio) -->
        <div id="viewport-canvas" class="relative mt-4 aspect-video bg-slate-950 rounded-xl border border-slate-800 overflow-hidden flex items-center justify-center">
          <!-- Background Grid Overlay -->
          <div class="absolute inset-0 opacity-20 pointer-events-none" style="background-image: radial-gradient(#38bdf8 1px, transparent 1px); background-size: 24px 24px;"></div>

          <!-- Active Target Card inside Viewport -->
          <div id="canvas-target-box" class="absolute hidden transition-all duration-300 ease-out border-2 border-cyan-400 bg-cyan-500/10 rounded-lg flex items-center justify-center shadow-lg shadow-cyan-500/30">
            <div class="absolute -top-6 left-0 bg-cyan-950 border border-cyan-700 text-cyan-300 text-[10px] font-mono px-1.5 py-0.5 rounded shadow">
              <span id="canvas-target-label">Target</span>
            </div>
            <!-- Crosshair ping -->
            <div class="h-4 w-4 rounded-full bg-cyan-400 reticle-ping"></div>
          </div>

          <!-- Speech Bubble Overlay (for pitch / DM) -->
          <div id="canvas-speech-bubble" class="absolute bottom-6 left-6 right-6 hidden bg-indigo-950/90 border border-indigo-700 backdrop-blur rounded-xl p-3 shadow-2xl transition-all">
            <div class="flex items-center gap-1.5 text-xs font-bold text-indigo-300 mb-1">
              <span>💬</span> <span id="speech-bubble-title">Instagram DM Pitch</span>
            </div>
            <p id="speech-bubble-body" class="text-xs text-indigo-100 font-mono leading-relaxed max-h-24 overflow-y-auto custom-scroll"></p>
          </div>

          <!-- Empty state when idle -->
          <div id="canvas-idle-state" class="flex flex-col items-center justify-center text-slate-600 text-xs">
            <span class="text-3xl mb-2">🔭</span>
            <span>Awaiting Desktop Agent Clicks or Dispatches...</span>
          </div>
        </div>

        <!-- Target Metadata Summary -->
        <div class="mt-4 p-3 bg-slate-950 rounded-xl border border-slate-800/80 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div>
            <span class="text-slate-500">Active Entity:</span>
            <span id="meta-entity" class="font-bold text-white ml-1.5">None</span>
          </div>
          <div>
            <span class="text-slate-500">Handle:</span>
            <span id="meta-handle" class="font-mono text-indigo-400 ml-1.5">@---</span>
          </div>
          <div>
            <span class="text-slate-500">Lead ID:</span>
            <span id="meta-lead-id" class="font-mono text-slate-300 ml-1.5">---</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: Real-Time Event Feed Stream -->
    <div class="lg:col-span-5 flex flex-col space-y-4">
      <div class="bg-slate-900/80 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-col h-[520px]">
        <div class="flex items-center justify-between pb-3 border-b border-slate-800">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold uppercase tracking-wider text-slate-300">Live Execution Feed</span>
            <span id="event-count-badge" class="text-[10px] mono px-2 py-0.5 rounded bg-slate-800 text-slate-400">0 events</span>
          </div>
          <div class="flex items-center gap-2">
            <label class="text-[11px] text-slate-400 flex items-center gap-1 cursor-pointer">
              <input type="checkbox" id="auto-scroll-toggle" checked class="accent-indigo-500"> Auto-scroll
            </label>
          </div>
        </div>

        <!-- Scrollable Event Stream List -->
        <div id="feed-container" class="flex-1 overflow-y-auto custom-scroll py-3 space-y-2.5">
          <!-- Live cards dynamically injected here -->
        </div>
      </div>
    </div>

  </main>

  <script>
    let isPaused = false;
    let totalEvents = 0;
    let kpis = { dm: 0, email: 0, warmup: 0, skip: 0, inbound: 0 };
    let knownIndices = new Set();

    async function pollEvents() {
      try {
        const res = await fetch('/api/events');
        if (!res.ok) return;
        const data = await res.json();
        processNewEvents(data.events || []);
      } catch (e) {
        console.error('Polling error:', e);
      }
    }

    function processNewEvents(events) {
      const container = document.getElementById('feed-container');
      const autoScroll = document.getElementById('auto-scroll-toggle').checked;

      events.forEach(ev => {
        if (knownIndices.has(ev.index)) return;
        knownIndices.add(ev.index);
        totalEvents++;

        // Update KPIs
        if (ev.action.includes('dm_sent')) kpis.dm++;
        if (ev.action.includes('email_sent')) kpis.email++;
        if (ev.action.includes('story') || ev.action.includes('like') || ev.action.includes('warmup')) kpis.warmup++;
        if (ev.action.includes('skip') || ev.action.includes('fail')) kpis.skip++;
        if (ev.action.includes('inbound')) kpis.inbound++;

        updateKpiDisplay();
        updateVisionOverlay(ev);

        // Append card
        const card = createEventCard(ev);
        container.appendChild(card);
      });

      document.getElementById('event-count-badge').textContent = `${totalEvents} events`;
      if (autoScroll && events.length > 0) {
        container.scrollTop = container.scrollHeight;
      }
    }

    function updateKpiDisplay() {
      document.getElementById('kpi-total').textContent = totalEvents;
      document.getElementById('kpi-dm').textContent = kpis.dm;
      document.getElementById('kpi-email').textContent = kpis.email;
      document.getElementById('kpi-warmup').textContent = kpis.warmup;
      document.getElementById('kpi-skip').textContent = kpis.skip;
      document.getElementById('kpi-inbound').textContent = kpis.inbound;
    }

    function updateVisionOverlay(ev) {
      document.getElementById('canvas-idle-state').classList.add('hidden');
      document.getElementById('meta-entity').textContent = ev.business_name || 'General';
      document.getElementById('meta-handle').textContent = ev.ig_handle && ev.ig_handle !== '-' ? `@${ev.ig_handle}` : '@---';
      document.getElementById('meta-lead-id').textContent = ev.lead_id || '---';

      const targetBox = document.getElementById('canvas-target-box');
      const coordsBadge = document.getElementById('coords-badge');
      const speechBubble = document.getElementById('canvas-speech-bubble');

      // Check bounds in details
      const bounds = ev.details && ev.details.bounds ? ev.details.bounds : null;
      if (bounds && bounds.width && bounds.height) {
        // Normalize bounds to 1920x1080 canvas
        const leftPct = (bounds.x / 1920) * 100;
        const topPct = (bounds.y / 1080) * 100;
        const widthPct = Math.max(8, (bounds.width / 1920) * 100);
        const heightPct = Math.max(5, (bounds.height / 1080) * 100);

        targetBox.style.left = `${leftPct}%`;
        targetBox.style.top = `${topPct}%`;
        targetBox.style.width = `${widthPct}%`;
        targetBox.style.height = `${heightPct}%`;
        targetBox.classList.remove('hidden');

        document.getElementById('canvas-target-label').textContent = ev.notes || ev.action;
        coordsBadge.textContent = `Target: x=${bounds.x}, y=${bounds.y} (${bounds.width}x${bounds.height})`;
      } else {
        // Fallback target highlight in center
        targetBox.style.left = '35%';
        targetBox.style.top = '40%';
        targetBox.style.width = '30%';
        targetBox.style.height = '20%';
        targetBox.classList.remove('hidden');
        document.getElementById('canvas-target-label').textContent = ev.action;
        coordsBadge.textContent = `Action: ${ev.action}`;
      }

      // Check pitch or message bubble
      const pitch = ev.pitch || (ev.details && ev.details.pitch);
      const emailPreview = ev.body_preview || (ev.details && ev.details.body_preview);
      if (pitch || emailPreview) {
        speechBubble.classList.remove('hidden');
        document.getElementById('speech-bubble-title').textContent = pitch ? 'Instagram DM Pitch' : 'Direct Email Dispatch';
        document.getElementById('speech-bubble-body').textContent = pitch || emailPreview;
      } else {
        speechBubble.classList.add('hidden');
      }
    }

    function createEventCard(ev) {
      const div = document.createElement('div');
      div.className = 'bg-slate-950/80 border border-slate-800/80 rounded-xl p-3 text-xs shadow transition hover:border-slate-700';

      let badgeColor = 'bg-slate-800 text-slate-300 border-slate-700';
      if (ev.action.includes('dm_sent')) badgeColor = 'bg-emerald-950 text-emerald-300 border-emerald-800';
      else if (ev.action.includes('email_sent')) badgeColor = 'bg-sky-950 text-sky-300 border-sky-800';
      else if (ev.action.includes('pitch')) badgeColor = 'bg-indigo-950 text-indigo-300 border-indigo-800';
      else if (ev.action.includes('story') || ev.action.includes('like')) badgeColor = 'bg-amber-950 text-amber-300 border-amber-800';
      else if (ev.action.includes('skip') || ev.action.includes('fail')) badgeColor = 'bg-rose-950 text-rose-300 border-rose-800';
      else if (ev.action.includes('inbound')) badgeColor = 'bg-purple-950 text-purple-300 border-purple-800';

      div.innerHTML = `
        <div class="flex items-center justify-between gap-2">
          <span class="px-2 py-0.5 rounded border font-mono text-[11px] ${badgeColor}">
            ${ev.action}
          </span>
          <span class="text-slate-500 font-mono text-[10px]">${ev.timestamp ? ev.timestamp.slice(11, 19) : ''} #${ev.index}</span>
        </div>
        <div class="mt-1.5 flex items-baseline gap-2">
          <span class="font-bold text-white text-xs">${escapeHtml(ev.business_name)}</span>
          ${ev.ig_handle && ev.ig_handle !== '-' ? `<span class="text-slate-400 font-mono text-[11px]">@${escapeHtml(ev.ig_handle)}</span>` : ''}
        </div>
        ${ev.notes ? `<p class="mt-1 text-slate-300 text-[11px] leading-relaxed">${escapeHtml(ev.notes)}</p>` : ''}
      `;
      return div;
    }

    function escapeHtml(text) {
      if (!text) return '';
      return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    async function toggleInterlock() {
      const btn = document.getElementById('btn-interlock');
      const badge = document.getElementById('hud-status-badge');
      const action = isPaused ? 'resume' : 'pause';

      try {
        const res = await fetch(`/api/control?action=${action}`, { method: 'POST' });
        const data = await res.json();
        isPaused = data.paused;

        if (isPaused) {
          btn.className = 'px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs tracking-wide transition flex items-center gap-2 shadow-lg shadow-emerald-600/30';
          document.getElementById('interlock-icon').textContent = '▶';
          document.getElementById('interlock-text').textContent = 'Resume Agent';
          badge.className = 'text-xs font-mono px-2 py-0.5 rounded bg-rose-950/80 border border-rose-800 text-rose-400 flex items-center gap-1.5';
          badge.innerHTML = '<span class="h-1.5 w-1.5 rounded-full bg-rose-400"></span> PAUSED BY HUMAN';
        } else {
          btn.className = 'px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs tracking-wide transition flex items-center gap-2 shadow-lg shadow-rose-600/30';
          document.getElementById('interlock-icon').textContent = '⏸';
          document.getElementById('interlock-text').textContent = 'Pause Agent';
          badge.className = 'text-xs font-mono px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800 text-emerald-400 flex items-center gap-1.5';
          badge.innerHTML = '<span class="h-1.5 w-1.5 rounded-full bg-emerald-400 pulse-dot"></span> LIVE SIDECAR';
        }
      } catch (e) {
        console.error('Interlock error:', e);
      }
    }

    function clearEventLogs() {
      document.getElementById('feed-container').innerHTML = '';
      knownIndices.clear();
      totalEvents = 0;
      kpis = { dm: 0, email: 0, warmup: 0, skip: 0, inbound: 0 };
      updateKpiDisplay();
      document.getElementById('event-count-badge').textContent = '0 events';
    }

    // Polling interval (every 800ms)
    setInterval(pollEvents, 800);
    pollEvents();
  </script>
</body>
</html>
"""


class HudServer(http.server.BaseHTTPRequestHandler):
    log_path: Path
    pause_file: Path
    last_read_line: int = 0

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            content = HUD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path.startswith("/api/events"):
            events = self.read_latest_events()
            body = json.dumps({"events": events}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/status"):
            is_paused = self.pause_file.exists()
            body = json.dumps({"paused": is_paused, "file": str(self.log_path)}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/control"):
            query = self.path.split("?")[-1] if "?" in self.path else ""
            action = "toggle"
            for param in query.split("&"):
                if param.startswith("action="):
                    action = param.split("=")[-1]

            if action == "pause":
                self.pause_file.write_text("PAUSED", encoding="utf-8")
            elif action == "resume":
                if self.pause_file.exists():
                    self.pause_file.unlink()
            else:
                if self.pause_file.exists():
                    self.pause_file.unlink()
                else:
                    self.pause_file.write_text("PAUSED", encoding="utf-8")

            is_paused = self.pause_file.exists()
            body = json.dumps({"paused": is_paused}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def read_latest_events(self) -> list[dict]:
        events: list[dict] = []
        if not self.log_path.exists():
            return events

        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            # If initial read, return last 40 events
            start_idx = 0 if self.last_read_line == 0 else self.last_read_line
            if self.last_read_line == 0 and len(lines) > 40:
                start_idx = len(lines) - 40

            for idx in range(start_idx, len(lines)):
                raw = lines[idx].strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                    events.append({
                        "index": idx + 1,
                        "timestamp": record.get("timestamp", ""),
                        "action": record.get("action", "event"),
                        "lead_id": record.get("lead_id", "-"),
                        "business_name": record.get("business_name") or record.get("title") or "-",
                        "ig_handle": record.get("ig_handle", "-"),
                        "notes": record.get("notes") or record.get("snippet") or "",
                        "pitch": (record.get("details") or {}).get("pitch"),
                        "body_preview": (record.get("details") or {}).get("body_preview"),
                        "details": record.get("details") or {},
                    })
                except Exception:
                    continue

            self.last_read_line = len(lines)
        except Exception as e:
            print(f"Error reading log: {e}", file=sys.stderr)

        return events

    def log_message(self, format, *args):
        # Suppress routine HTTP GET polling logs in terminal
        return


def run_hud(log_file: Path, port: int, open_browser: bool) -> None:
    HudServer.log_path = log_file.resolve()
    HudServer.pause_file = log_file.parent / ".cowork-pause"

    url = f"http://localhost:{port}/"
    print(f"=================================================================")
    print(f"           COWORK LIVE VISION HUD & REAL-TIME SIDECAR            ")
    print(f"=================================================================")
    print(f"  Streaming log:  {HudServer.log_path}")
    print(f"  Pause lock:     {HudServer.pause_file}")
    print(f"  Live Dashboard: {url}")
    print(f"=================================================================")

    if open_browser:
        webbrowser.open(url)

    server = socketserver.TCPServer(("", port), HudServer)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nHUD stopped by user.")
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Desktop Cowork HUD & Real-Time Vision Overlay")
    parser.add_argument("--log", "-l", default=None, help="Path to business_logs.jsonl or event stream")
    parser.add_argument("--port", "-p", type=int, default=8765, help="HUD server port (default: 8765)")
    parser.add_argument("--open", action="store_true", help="Launch HUD in browser automatically")
    args = parser.parse_args()

    target: Path | None = None
    if args.log:
        target = Path(args.log)
    else:
        candidates = [
            Path("business_logs.jsonl"),
            Path("emiliano-cowork-plaatoos/business_logs.jsonl"),
            Path("../emiliano-cowork-plaatoos/business_logs.jsonl"),
        ]
        for c in candidates:
            if c.exists():
                target = c
                break

    if not target or not target.exists():
        print(f"Error: Log file not found. Provide --log path/to/business_logs.jsonl")
        return 1

    run_hud(target, args.port, args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
