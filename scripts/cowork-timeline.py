#!/usr/bin/env python3
"""
Agent Cowork & Execution Timeline Replay Dashboard.
Part of the agent-standards ecosystem.

Parses structured JSONL event streams (e.g. business_logs.jsonl, inbound_replies.jsonl,
agent execution traces, or transcripts) and compiles an interactive, visual timeline
dashboard with live playback scrubber, KPI scorecard, lead journey inspector, and payload drawer.

Usage:
    python scripts/cowork-timeline.py [path_to_log.jsonl] [--open] [--out path.html] [--title "Title"]
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import sys
import webbrowser
from pathlib import Path


def parse_timestamp(ts_str: str | None) -> datetime.datetime | None:
    if not ts_str:
        return None
    try:
        clean_ts = ts_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(clean_ts)
    except Exception:
        try:
            return datetime.datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem_sec = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {rem_sec}s"
    hours = int(minutes // 60)
    rem_min = int(minutes % 60)
    return f"{hours}h {rem_min}m"


def load_events(log_path: Path) -> list[dict]:
    events: list[dict] = []
    if not log_path.exists():
        return events

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    prev_dt: datetime.datetime | None = None

    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue

        ts_val = record.get("timestamp") or record.get("date") or record.get("time") or record.get("created_at")
        cur_dt = parse_timestamp(ts_val)

        delta_sec = 0.0
        if cur_dt and prev_dt:
            delta = (cur_dt - prev_dt).total_seconds()
            if delta >= 0:
                delta_sec = delta
        if cur_dt:
            prev_dt = cur_dt

        action = record.get("action")
        if not action:
            if "snippet" in record and "title" in record:
                action = "inbound_reply"
            elif "tool_call" in record:
                action = record.get("tool_name", "tool_call")
            elif "role" in record:
                action = f"turn_{record['role']}"
            else:
                action = "event"

        lead_id = record.get("lead_id") or record.get("id") or record.get("lead") or "-"
        business_name = record.get("business_name") or record.get("clean_title") or record.get("title") or record.get("name") or "-"
        ig_handle = record.get("ig_handle") or record.get("handle") or "-"
        business_type = record.get("business_type") or record.get("category") or "general"
        notes = record.get("notes") or record.get("snippet") or record.get("message") or record.get("summary") or ""
        details = record.get("details") or {}
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {"raw": details}

        pitch = details.get("pitch") if isinstance(details, dict) else None
        body_preview = details.get("body_preview") if isinstance(details, dict) else None
        subject = details.get("subject") if isinstance(details, dict) else None

        events.append({
            "index": idx + 1,
            "timestamp": ts_val or "",
            "dt_iso": cur_dt.isoformat() if cur_dt else "",
            "delta_sec": delta_sec,
            "delta_str": f"+{format_duration(delta_sec)}" if delta_sec > 0 else "0.0s",
            "action": action,
            "lead_id": lead_id,
            "business_name": business_name,
            "ig_handle": ig_handle,
            "business_type": business_type,
            "notes": notes,
            "pitch": pitch,
            "body_preview": body_preview,
            "subject": subject,
            "details": details,
            "raw": record,
        })

    return events


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__TITLE__</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    code, pre, .mono {
      font-family: 'JetBrains Mono', monospace;
    }
    .custom-scroll::-webkit-scrollbar {
      width: 6px;
      height: 6px;
    }
    .custom-scroll::-webkit-scrollbar-track {
      background: #0f172a;
    }
    .custom-scroll::-webkit-scrollbar-thumb {
      background: #334155;
      border-radius: 3px;
    }
    .custom-scroll::-webkit-scrollbar-thumb:hover {
      background: #475569;
    }
    .pulse-dot {
      animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: .3; }
    }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen antialiased selection:bg-indigo-500 selection:text-white flex flex-col">

  <!-- Header -->
  <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 rounded-xl bg-gradient-to-tr from-emerald-500 via-teal-500 to-indigo-600 flex items-center justify-center font-bold text-white shadow-lg shadow-emerald-500/20">
          ⚡
        </div>
        <div>
          <div class="flex items-center gap-2">
            <span class="font-bold text-base tracking-tight text-white">__TITLE__</span>
            <span class="text-xs text-emerald-400 font-mono px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800 flex items-center gap-1.5">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 pulse-dot"></span> Replay Engine
            </span>
          </div>
          <p class="text-xs text-slate-400 font-mono mt-0.5">Stream: __LOG_NAME__ &bull; Total Span: __DURATION_STR__</p>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <button onclick="window.print()" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 transition text-xs font-medium border border-slate-700 flex items-center gap-1.5">
          <span>🖨️</span> Print / PDF
        </button>
      </div>
    </div>
  </header>

  <!-- KPI Scorecard -->
  <section class="max-w-7xl mx-auto px-6 py-6 w-full">
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Total Steps</span>
        <span class="text-2xl font-extrabold text-white mt-1 mono">__TOTAL_EVENTS__</span>
        <span class="text-[11px] text-slate-500 mt-0.5">Recorded events</span>
      </div>
      <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-semibold uppercase tracking-wider text-emerald-400">DMs Dispatched</span>
        <span class="text-2xl font-extrabold text-emerald-300 mt-1 mono">__DM_COUNT__</span>
        <span class="text-[11px] text-slate-500 mt-0.5">Verified sends</span>
      </div>
      <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-semibold uppercase tracking-wider text-sky-400">Emails Sent</span>
        <span class="text-2xl font-extrabold text-sky-300 mt-1 mono">__EMAIL_COUNT__</span>
        <span class="text-[11px] text-slate-500 mt-0.5">Direct outreach</span>
      </div>
      <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-semibold uppercase tracking-wider text-amber-400">Warm-ups</span>
        <span class="text-2xl font-extrabold text-amber-300 mt-1 mono">__WARMUP_COUNT__</span>
        <span class="text-[11px] text-slate-500 mt-0.5">Stories & likes</span>
      </div>
      <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-semibold uppercase tracking-wider text-rose-400">Skipped / 404</span>
        <span class="text-2xl font-extrabold text-rose-300 mt-1 mono">__SKIP_COUNT__</span>
        <span class="text-[11px] text-slate-500 mt-0.5">Clean triage</span>
      </div>
      <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col">
        <span class="text-xs font-semibold uppercase tracking-wider text-indigo-400">Unique Leads</span>
        <span class="text-2xl font-extrabold text-indigo-300 mt-1 mono">__UNIQUE_LEADS__</span>
        <span class="text-[11px] text-slate-500 mt-0.5">Pipeline entities</span>
      </div>
    </div>
  </section>

  <!-- Interactive Scrubber & Controls -->
  <section class="max-w-7xl mx-auto px-6 pb-4 w-full">
    <div class="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 shadow-xl">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <!-- Play / Pause & Controls -->
        <div class="flex items-center gap-3">
          <button id="btn-play" onclick="togglePlay()" class="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs tracking-wide transition flex items-center gap-2 shadow-lg shadow-emerald-600/30">
            <span id="play-icon">▶</span> <span id="play-text">Replay Stream</span>
          </button>
          <button onclick="resetPlayback()" class="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition text-xs border border-slate-700" title="Reset to Beginning">
            ⏮
          </button>
          <div class="flex items-center bg-slate-950 rounded-xl border border-slate-800 p-1 text-xs mono">
            <span class="text-slate-400 px-2">Speed:</span>
            <button onclick="setSpeed(1)" class="speed-btn px-2 py-0.5 rounded text-emerald-400 font-bold bg-slate-800" data-speed="1">1x</button>
            <button onclick="setSpeed(2)" class="speed-btn px-2 py-0.5 rounded text-slate-400 hover:text-white" data-speed="2">2x</button>
            <button onclick="setSpeed(5)" class="speed-btn px-2 py-0.5 rounded text-slate-400 hover:text-white" data-speed="5">5x</button>
            <button onclick="setSpeed(10)" class="speed-btn px-2 py-0.5 rounded text-slate-400 hover:text-white" data-speed="10">10x</button>
          </div>
        </div>

        <!-- Scrubber Slider -->
        <div class="flex-1 flex items-center gap-4 px-2">
          <input type="range" id="time-slider" min="1" max="__TOTAL_EVENTS_OR_1__" value="__TOTAL_EVENTS_OR_1__" oninput="onSliderChange(this.value)" class="w-full accent-emerald-500 cursor-pointer">
          <span id="step-badge" class="text-xs font-mono px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 whitespace-nowrap min-w-[120px] text-center">
            Step __TOTAL_EVENTS__ / __TOTAL_EVENTS__
          </span>
        </div>

        <!-- Jump Helpers -->
        <div class="flex items-center gap-2">
          <button onclick="jumpToNext('dm_sent')" class="px-2.5 py-1.5 rounded-lg bg-emerald-950 hover:bg-emerald-900 border border-emerald-800 text-emerald-300 text-xs font-medium transition" title="Jump to next DM Sent">
            Next DM ➔
          </button>
          <button onclick="jumpToNext('email_sent')" class="px-2.5 py-1.5 rounded-lg bg-sky-950 hover:bg-sky-900 border border-sky-800 text-sky-300 text-xs font-medium transition" title="Jump to next Email Sent">
            Next Email ➔
          </button>
          <button onclick="jumpToNext('lead_skipped')" class="px-2.5 py-1.5 rounded-lg bg-rose-950 hover:bg-rose-900 border border-rose-800 text-rose-300 text-xs font-medium transition" title="Jump to next Skip / 404">
            Next Skip ➔
          </button>
        </div>
      </div>
    </div>
  </section>

  <!-- Filter & Search Toolbar -->
  <section class="max-w-7xl mx-auto px-6 pb-4 w-full">
    <div class="flex flex-col md:flex-row md:items-center justify-between gap-3">
      <!-- Action Filters -->
      <div class="flex flex-wrap items-center gap-1.5 text-xs">
        <button onclick="setFilter('all')" class="filter-btn px-3 py-1.5 rounded-lg bg-indigo-600 text-white font-semibold transition" data-filter="all">
          All (__TOTAL_EVENTS__)
        </button>
        <button onclick="setFilter('dm')" class="filter-btn px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-emerald-400 transition" data-filter="dm">
          DMs (__DM_COUNT__)
        </button>
        <button onclick="setFilter('email')" class="filter-btn px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-sky-400 transition" data-filter="email">
          Emails (__EMAIL_COUNT__)
        </button>
        <button onclick="setFilter('warmup')" class="filter-btn px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-amber-400 transition" data-filter="warmup">
          Warm-ups (__WARMUP_COUNT__)
        </button>
        <button onclick="setFilter('skip')" class="filter-btn px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-rose-400 transition" data-filter="skip">
          Skips (__SKIP_COUNT__)
        </button>
        <button onclick="setFilter('inbound')" class="filter-btn px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-purple-400 transition" data-filter="inbound">
          Inbounds (__INBOUND_COUNT__)
        </button>
      </div>

      <!-- Search Input -->
      <div class="flex items-center gap-2">
        <div class="relative">
          <input type="text" id="search-input" placeholder="Search business, lead, handle, pitch..." oninput="onSearchChange(this.value)" class="bg-slate-900 border border-slate-800 rounded-xl px-3.5 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-64 mono">
          <button onclick="clearSearch()" id="clear-search-btn" class="hidden absolute right-2.5 top-1.5 text-slate-500 hover:text-slate-300 text-xs">✕</button>
        </div>
        <div id="lead-filter-badge" class="hidden text-xs bg-indigo-950 border border-indigo-800 text-indigo-300 px-2.5 py-1 rounded-xl flex items-center gap-1.5">
          <span id="lead-filter-name">Lead: PL-001</span>
          <button onclick="clearLeadFilter()" class="hover:text-white font-bold ml-1">✕</button>
        </div>
      </div>
    </div>
  </section>

  <!-- Main Timeline Container -->
  <main class="max-w-7xl mx-auto px-6 pb-16 w-full flex-1">
    <div id="timeline-container" class="relative pl-6 border-l-2 border-slate-800 space-y-4">
      <!-- Dynamic Event Cards rendered here by JS -->
    </div>
    <div id="no-events-view" class="hidden py-16 text-center text-slate-500 text-sm">
      No matching events found for current filter or search criteria.
    </div>
  </main>

  <!-- Embedded JSON Data -->
  <script id="timeline-data" type="application/json">
__EVENTS_JSON__
  </script>

  <!-- Application Logic -->
  <script>
    const rawEvents = JSON.parse(document.getElementById('timeline-data').textContent);
    let currentLimit = rawEvents.length;
    let activeFilter = 'all';
    let searchQuery = '';
    let selectedLeadId = null;
    let isPlaying = false;
    let playSpeed = 1;
    let playTimer = null;

    function getActionConfig(action) {
      if (action.includes('dm_sent')) {
        return {
          icon: '🚀',
          color: 'emerald',
          badgeClass: 'bg-emerald-950/90 text-emerald-300 border-emerald-800',
          dotClass: 'bg-emerald-500 ring-4 ring-emerald-950',
          title: 'Instagram DM Sent'
        };
      }
      if (action.includes('pitch_dispatched')) {
        return {
          icon: '💬',
          color: 'indigo',
          badgeClass: 'bg-indigo-950/90 text-indigo-300 border-indigo-800',
          dotClass: 'bg-indigo-500 ring-4 ring-indigo-950',
          title: 'Pitch Bubble Dispatched'
        };
      }
      if (action.includes('email_sent')) {
        return {
          icon: '✉️',
          color: 'sky',
          badgeClass: 'bg-sky-950/90 text-sky-300 border-sky-800',
          dotClass: 'bg-sky-500 ring-4 ring-sky-950',
          title: 'Email Sent'
        };
      }
      if (action.includes('email_enriched')) {
        return {
          icon: '🔍',
          color: 'cyan',
          badgeClass: 'bg-cyan-950/90 text-cyan-300 border-cyan-800',
          dotClass: 'bg-cyan-500 ring-4 ring-cyan-950',
          title: 'Email Enriched'
        };
      }
      if (action.includes('story_watched')) {
        return {
          icon: '👁️',
          color: 'amber',
          badgeClass: 'bg-amber-950/90 text-amber-300 border-amber-800',
          dotClass: 'bg-amber-500 ring-4 ring-amber-950',
          title: 'Story / Highlight Watched'
        };
      }
      if (action.includes('post_liked')) {
        return {
          icon: '❤️',
          color: 'rose',
          badgeClass: 'bg-rose-950/90 text-rose-300 border-rose-800',
          dotClass: 'bg-rose-500 ring-4 ring-rose-950',
          title: 'Post Liked'
        };
      }
      if (action.includes('social_warmup')) {
        return {
          icon: '🔥',
          color: 'amber',
          badgeClass: 'bg-amber-950/90 text-amber-300 border-amber-800',
          dotClass: 'bg-amber-500 ring-4 ring-amber-950',
          title: 'Social Warm-up'
        };
      }
      if (action.includes('dm_opened')) {
        return {
          icon: '📨',
          color: 'purple',
          badgeClass: 'bg-purple-950/90 text-purple-300 border-purple-800',
          dotClass: 'bg-purple-500 ring-4 ring-purple-950',
          title: 'DM Modal Opened'
        };
      }
      if (action.includes('outreach_started')) {
        return {
          icon: '🎬',
          color: 'blue',
          badgeClass: 'bg-blue-950/90 text-blue-300 border-blue-800',
          dotClass: 'bg-blue-500 ring-4 ring-blue-950',
          title: 'Outreach Started'
        };
      }
      if (action.includes('navigated')) {
        return {
          icon: '🧭',
          color: 'slate',
          badgeClass: 'bg-slate-900 text-slate-300 border-slate-700',
          dotClass: 'bg-slate-400 ring-4 ring-slate-900',
          title: 'Navigated to Profile'
        };
      }
      if (action.includes('skip') || action.includes('fail')) {
        return {
          icon: '⛔',
          color: 'rose',
          badgeClass: 'bg-rose-950/90 text-rose-300 border-rose-800',
          dotClass: 'bg-rose-500 ring-4 ring-rose-950',
          title: 'Lead Skipped / Triage'
        };
      }
      if (action.includes('inbound')) {
        return {
          icon: '📥',
          color: 'violet',
          badgeClass: 'bg-violet-950/90 text-violet-300 border-violet-800',
          dotClass: 'bg-violet-500 ring-4 ring-violet-950',
          title: 'Inbound Reply'
        };
      }
      return {
        icon: '🔹',
        color: 'slate',
        badgeClass: 'bg-slate-900 text-slate-300 border-slate-700',
        dotClass: 'bg-slate-500 ring-4 ring-slate-900',
        title: action
      };
    }

    function renderTimeline() {
      const container = document.getElementById('timeline-container');
      const noEvents = document.getElementById('no-events-view');

      const visibleSlice = rawEvents.slice(0, currentLimit);

      const filtered = visibleSlice.filter(ev => {
        if (selectedLeadId && ev.lead_id !== selectedLeadId) {
          return false;
        }

        if (activeFilter === 'dm' && !ev.action.includes('dm') && !ev.action.includes('pitch')) return false;
        if (activeFilter === 'email' && !ev.action.includes('email')) return false;
        if (activeFilter === 'warmup' && !ev.action.includes('story') && !ev.action.includes('like') && !ev.action.includes('warmup')) return false;
        if (activeFilter === 'skip' && !ev.action.includes('skip') && !ev.action.includes('fail')) return false;
        if (activeFilter === 'inbound' && !ev.action.includes('inbound')) return false;

        if (searchQuery) {
          const q = searchQuery.toLowerCase();
          const targetStr = `${ev.business_name} ${ev.lead_id} ${ev.ig_handle} ${ev.notes} ${ev.action} ${ev.pitch || ''} ${ev.subject || ''}`.toLowerCase();
          if (!targetStr.includes(q)) return false;
        }

        return true;
      });

      if (filtered.length === 0) {
        container.innerHTML = '';
        noEvents.classList.remove('hidden');
        return;
      }
      noEvents.classList.add('hidden');

      const htmlBlocks = filtered.map(ev => {
        const cfg = getActionConfig(ev.action);
        const pitchBlock = ev.pitch ? `
          <div class="mt-3 bg-indigo-950/40 border-l-2 border-indigo-500 rounded-r-lg p-3 text-xs text-indigo-200">
            <span class="font-semibold text-indigo-300 block mb-1">💬 Pitch Bubble:</span>
            <p class="whitespace-pre-wrap">${escapeHtml(ev.pitch)}</p>
          </div>
        ` : '';

        const emailBlock = (ev.subject || ev.body_preview) ? `
          <div class="mt-3 bg-sky-950/40 border-l-2 border-sky-500 rounded-r-lg p-3 text-xs text-sky-200">
            ${ev.subject ? `<div class="font-semibold text-sky-300 mb-1">Subject: ${escapeHtml(ev.subject)}</div>` : ''}
            ${ev.body_preview ? `<div class="whitespace-pre-wrap text-slate-300 font-mono text-[11px]">${escapeHtml(ev.body_preview)}</div>` : ''}
          </div>
        ` : '';

        const jsonDetails = Object.keys(ev.details || {}).length > 0 ? `
          <details class="mt-3 text-xs">
            <summary class="cursor-pointer text-slate-400 hover:text-slate-300 font-mono text-[11px]">▶ View JSON Payload</summary>
            <pre class="mt-2 p-3 bg-slate-950 rounded-lg border border-slate-800 text-[11px] mono text-emerald-400 overflow-x-auto">${escapeHtml(JSON.stringify(ev.details, null, 2))}</pre>
          </details>
        ` : '';

        return `
          <div class="relative group" id="card-${ev.index}">
            <div class="absolute -left-[31px] top-4 h-4 w-4 rounded-full ${cfg.dotClass} transition-transform group-hover:scale-125"></div>

            <div class="bg-slate-900/80 hover:bg-slate-900 border border-slate-800/90 rounded-2xl p-4 shadow-lg transition duration-150">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex items-center gap-2">
                  <span class="px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 ${cfg.badgeClass}">
                    <span>${cfg.icon}</span> ${cfg.title}
                  </span>
                  ${ev.lead_id && ev.lead_id !== '-' ? `
                    <button onclick="selectLead('${ev.lead_id}')" class="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition" title="Filter to this Lead">
                      ${escapeHtml(ev.lead_id)}
                    </button>
                  ` : ''}
                  ${ev.business_type && ev.business_type !== 'general' ? `
                    <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-950 text-slate-400 border border-slate-800">
                      ${escapeHtml(ev.business_type)}
                    </span>
                  ` : ''}
                </div>
                <div class="flex items-center gap-3 text-xs text-slate-400 font-mono">
                  ${ev.delta_sec > 0 ? `<span class="text-emerald-400/80">${ev.delta_str}</span> &bull;` : ''}
                  <span>${ev.timestamp ? ev.timestamp.replace('T', ' ').slice(0, 19) : ''}</span>
                  <span class="text-slate-600">#${ev.index}</span>
                </div>
              </div>

              <div class="mt-2.5 flex items-baseline gap-2">
                <h3 class="text-sm font-bold text-white tracking-tight">${escapeHtml(ev.business_name)}</h3>
                ${ev.ig_handle && ev.ig_handle !== '-' ? `
                  <a href="https://instagram.com/${encodeURIComponent(ev.ig_handle)}" target="_blank" rel="noopener" class="text-xs font-mono text-indigo-400 hover:text-indigo-300 hover:underline">
                    @${escapeHtml(ev.ig_handle)}
                  </a>
                ` : ''}
              </div>

              ${ev.notes ? `
                <p class="mt-1.5 text-xs text-slate-300 leading-relaxed">${escapeHtml(ev.notes)}</p>
              ` : ''}

              ${pitchBlock}
              ${emailBlock}
              ${jsonDetails}
            </div>
          </div>
        `;
      }).join('');

      container.innerHTML = htmlBlocks;
    }

    function escapeHtml(text) {
      if (!text) return '';
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function onSliderChange(val) {
      currentLimit = parseInt(val, 10);
      updateStepBadge();
      renderTimeline();
    }

    function updateStepBadge() {
      const badge = document.getElementById('step-badge');
      const slider = document.getElementById('time-slider');
      slider.value = currentLimit;
      badge.textContent = `Step ${currentLimit} / ${rawEvents.length}`;
    }

    function togglePlay() {
      if (isPlaying) {
        pausePlayback();
      } else {
        startPlayback();
      }
    }

    function startPlayback() {
      if (currentLimit >= rawEvents.length) {
        currentLimit = 1;
      }
      isPlaying = true;
      document.getElementById('play-icon').textContent = '⏸';
      document.getElementById('play-text').textContent = 'Pause Replay';
      const intervalMs = Math.max(50, Math.floor(400 / playSpeed));

      playTimer = setInterval(() => {
        if (currentLimit < rawEvents.length) {
          currentLimit++;
          updateStepBadge();
          renderTimeline();

          const card = document.getElementById(`card-${currentLimit}`);
          if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        } else {
          pausePlayback();
        }
      }, intervalMs);
    }

    function pausePlayback() {
      isPlaying = false;
      if (playTimer) clearInterval(playTimer);
      document.getElementById('play-icon').textContent = '▶';
      document.getElementById('play-text').textContent = 'Replay Stream';
    }

    function resetPlayback() {
      pausePlayback();
      currentLimit = 1;
      updateStepBadge();
      renderTimeline();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function setSpeed(speed) {
      playSpeed = speed;
      document.querySelectorAll('.speed-btn').forEach(btn => {
        if (parseInt(btn.getAttribute('data-speed'), 10) === speed) {
          btn.className = 'speed-btn px-2 py-0.5 rounded text-emerald-400 font-bold bg-slate-800';
        } else {
          btn.className = 'speed-btn px-2 py-0.5 rounded text-slate-400 hover:text-white';
        }
      });
      if (isPlaying) {
        pausePlayback();
        startPlayback();
      }
    }

    function setFilter(filter) {
      activeFilter = filter;
      document.querySelectorAll('.filter-btn').forEach(btn => {
        if (btn.getAttribute('data-filter') === filter) {
          btn.className = 'filter-btn px-3 py-1.5 rounded-lg bg-indigo-600 text-white font-semibold transition';
        } else {
          btn.className = 'filter-btn px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300 transition';
        }
      });
      renderTimeline();
    }

    function onSearchChange(val) {
      searchQuery = val.trim();
      const clearBtn = document.getElementById('clear-search-btn');
      if (searchQuery) {
        clearBtn.classList.remove('hidden');
      } else {
        clearBtn.classList.add('hidden');
      }
      renderTimeline();
    }

    function clearSearch() {
      document.getElementById('search-input').value = '';
      searchQuery = '';
      document.getElementById('clear-search-btn').classList.add('hidden');
      renderTimeline();
    }

    function selectLead(leadId) {
      selectedLeadId = leadId;
      const badge = document.getElementById('lead-filter-badge');
      const name = document.getElementById('lead-filter-name');
      name.textContent = `Lead: ${leadId}`;
      badge.classList.remove('hidden');
      renderTimeline();
    }

    function clearLeadFilter() {
      selectedLeadId = null;
      document.getElementById('lead-filter-badge').classList.add('hidden');
      renderTimeline();
    }

    function jumpToNext(actionPattern) {
      for (let i = currentLimit; i < rawEvents.length; i++) {
        if (rawEvents[i].action.includes(actionPattern)) {
          currentLimit = i + 1;
          updateStepBadge();
          renderTimeline();
          const card = document.getElementById(`card-${currentLimit}`);
          if (card) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
          return;
        }
      }
      alert(`No further "${actionPattern}" events downstream.`);
    }

    updateStepBadge();
    renderTimeline();
  </script>
</body>
</html>
"""


def generate_html_dashboard(events: list[dict], log_name: str, title: str) -> str:
    total_events = len(events)
    dm_count = sum(1 for e in events if "dm_sent" in e["action"])
    email_count = sum(1 for e in events if "email_sent" in e["action"])
    warmup_count = sum(1 for e in events if any(k in e["action"] for k in ("story_watched", "post_liked", "social_warmup")))
    skip_count = sum(1 for e in events if "skip" in e["action"] or "fail" in e["action"])
    inbound_count = sum(1 for e in events if "inbound" in e["action"])
    unique_leads = len(set(e["lead_id"] for e in events if e["lead_id"] and e["lead_id"] != "-"))

    total_duration_sec = 0.0
    if events:
        first_dt = parse_timestamp(events[0]["timestamp"])
        last_dt = parse_timestamp(events[-1]["timestamp"])
        if first_dt and last_dt:
            total_duration_sec = max(0.0, (last_dt - first_dt).total_seconds())

    duration_str = format_duration(total_duration_sec)
    events_json = json.dumps(events)

    result = HTML_TEMPLATE
    replacements = {
        "__TITLE__": html.escape(title),
        "__LOG_NAME__": html.escape(log_name),
        "__DURATION_STR__": duration_str,
        "__TOTAL_EVENTS__": str(total_events),
        "__TOTAL_EVENTS_OR_1__": str(total_events or 1),
        "__DM_COUNT__": str(dm_count),
        "__EMAIL_COUNT__": str(email_count),
        "__WARMUP_COUNT__": str(warmup_count),
        "__SKIP_COUNT__": str(skip_count),
        "__INBOUND_COUNT__": str(inbound_count),
        "__UNIQUE_LEADS__": str(unique_leads),
        "__EVENTS_JSON__": events_json,
    }
    for token, val in replacements.items():
        result = result.replace(token, val)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Cowork & Execution Timeline Replay Dashboard")
    parser.add_argument("log_file", nargs="?", default=None, help="Path to JSONL log file (business_logs.jsonl or trace)")
    parser.add_argument("--out", "-o", default=None, help="Output HTML file path")
    parser.add_argument("--open", action="store_true", help="Launch directly in default browser")
    parser.add_argument("--title", "-t", default=None, help="Custom title for the dashboard")
    args = parser.parse_args()

    target_path: Path | None = None
    if args.log_file:
        target_path = Path(args.log_file)
    else:
        candidates = [
            Path("business_logs.jsonl"),
            Path("emiliano-cowork-plaatoos/business_logs.jsonl"),
            Path("../emiliano-cowork-plaatoos/business_logs.jsonl"),
            Path("inbound_replies.jsonl"),
        ]
        for c in candidates:
            if c.exists():
                target_path = c
                break

    if not target_path or not target_path.exists():
        print(f"Error: Log file not found. Please provide a path to a JSONL log file.")
        print(f"Usage: python scripts/cowork-timeline.py path/to/business_logs.jsonl --open")
        return 1

    print(f"Reading event stream: {target_path}")
    events = load_events(target_path)
    print(f"Parsed {len(events)} events from {target_path.name}")

    title = args.title or f"Agent Cowork Timeline &bull; {target_path.name}"
    html_content = generate_html_dashboard(events, target_path.name, title)

    out_path = Path(args.out) if args.out else target_path.with_suffix(".timeline.html")
    out_path.write_text(html_content, encoding="utf-8")
    print(f"Compiled interactive timeline dashboard -> {out_path.resolve()}")

    if args.open:
        print(f"Launching in default browser: {out_path.resolve()}")
        webbrowser.open(out_path.resolve().as_uri())

    return 0


if __name__ == "__main__":
    sys.exit(main())
