import React, { useState, useEffect } from 'react';
import { Play, Pause, Compass, ShieldAlert, X } from 'lucide-react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import type { HarnessType, HUDHighlightMessage } from '@emiliano/protocol';
import { isOverlayWindow, useEngineSocket } from './engine';

export default function App() {
  if (isOverlayWindow()) {
    return <HUDOverlayView />;
  }

  return <FloatingDockView />;
}

// -------------------------------------------------------------
// 1. HUD OVERLAY VIEW (Fullscreen Transparent Screen Layer)
// -------------------------------------------------------------
function HUDOverlayView() {
  const [highlight, setHighlight] = useState<HUDHighlightMessage['payload'] | null>(null);

  useEngineSocket((msg) => {
    if (msg.type === 'HUD_HIGHLIGHT') {
      setHighlight(msg.payload);
      setTimeout(() => setHighlight(null), msg.payload.durationMs || 2500);
    } else if (msg.type === 'HUD_CLEAR') {
      setHighlight(null);
    }
  });

  if (!highlight) return null;

  const { bounds, name, action } = highlight.element;

  return (
    <div className="w-screen h-screen pointer-events-none relative overflow-hidden">
      {/* Target Bounding Box */}
      <div
        className="absolute border-2 border-cyan-400 bg-cyan-400/20 rounded shadow-[0_0_15px_rgba(34,211,238,0.8)] transition-all duration-300 animate-pulse"
        style={{
          left: `${bounds.x}px`,
          top: `${bounds.y}px`,
          width: `${bounds.width}px`,
          height: `${bounds.height}px`,
        }}
      >
        <div className="absolute -top-7 left-0 bg-slate-900/90 text-cyan-300 text-xs px-2 py-0.5 rounded border border-cyan-500/40 flex items-center space-x-1 whitespace-nowrap">
          <span className="font-semibold">{action.toUpperCase()}</span>
          <span>•</span>
          <span>{name}</span>
        </div>
      </div>
    </div>
  );
}

// -------------------------------------------------------------
// 2. FLOATING DOCK VIEW (Claude Cowork Style Desktop Sidebar)
// -------------------------------------------------------------
function FloatingDockView() {
  const [goal, setGoal] = useState('');
  const [harness, setHarness] = useState<HarnessType>('auto');
  const [isRunning, setIsRunning] = useState(false);
  const [thoughts, setThoughts] = useState<string[]>([]);
  const logEndRef = React.useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [thoughts]);

  const ws = useEngineSocket(
    (msg) => {
      if (msg.type === 'THOUGHT_STREAM') {
        setThoughts((prev) => [...prev, msg.payload.chunk]);
      } else if (msg.type === 'DAG_UPDATE') {
        const status = msg.payload?.status;
        if (status === 'completed' || status === 'failed' || status === 'paused') {
          setIsRunning(false);
        }
      }
    },
    (socket) => socket.send(JSON.stringify({ type: 'GET_CAPABILITIES', payload: {} })),
  );

  // Emergency kill switch: the desktop shell sends this when Esc is pressed anywhere
  useEffect(() => {
    if (!isTauri()) return;
    const unlisten = listen('emergency-stop', () => {
      setIsRunning(false);
      try {
        ws?.send(JSON.stringify({ type: 'TASK_CANCEL', payload: {} }));
      } catch (e) {
        // Socket may already be closed
      }
      setThoughts((prev) => [...prev, '\n[STOP] Emergency stop triggered by User (Esc)\n']);
    });
    return () => {
      unlisten.then((stop) => stop());
    };
  }, [ws]);

  // Only capture Esc system-wide while a task runs, so it keeps working in other apps otherwise
  useEffect(() => {
    if (!isTauri()) return;
    invoke('set_kill_switch', { enabled: isRunning }).catch((e) => console.error('Kill switch:', e));
  }, [isRunning]);

  const handleStart = () => {
    if (!goal.trim()) return;
    setIsRunning(true);
    setThoughts([`Initiating objective: "${goal}"\nSelected harness: ${harness}\n`]);
    ws?.send(
      JSON.stringify({
        type: 'TASK_START',
        payload: {
          goal,
          harnessPreference: harness,
        },
      })
    );
  };

  const handleCancel = () => {
    setIsRunning(false);
    ws?.send(JSON.stringify({ type: 'TASK_CANCEL', payload: {} }));
  };

  return (
    <div className="w-full h-full p-3 flex flex-col justify-between">
      <div className="glass-panel rounded-2xl p-4 flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        {/* data-tauri-drag-region: the window is frameless, so the header moves it */}
        <div data-tauri-drag-region className="flex items-center justify-between pb-3 border-b border-slate-700/60 cursor-move">
          <div data-tauri-drag-region className="flex items-center space-x-2">
            <div className={`w-3 h-3 rounded-full ${ws ? 'bg-cyan-400 animate-ping' : 'bg-amber-400'}`} />
            <h1 data-tauri-drag-region className="text-base font-bold tracking-wide text-white">EMILIANO</h1>
          </div>
          <div className="flex items-center space-x-2">
            <span className="text-[11px] bg-cyan-950 text-cyan-300 border border-cyan-800 px-2 py-0.5 rounded-full font-mono">
              {ws ? 'COWORK v0.1' : 'Starting engine…'}
            </span>
            {isTauri() && (
              <button
                onClick={() => getCurrentWindow().close()}
                title="Quit Emiliano"
                className="text-slate-400 hover:text-white hover:bg-slate-700 rounded-md p-1 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Harness Selector */}
        <div className="mt-3">
          <label className="text-[11px] font-medium text-slate-400 mb-1 block">Active Harness Mode</label>
          <div className="grid grid-cols-3 gap-1.5 text-xs">
            {(['auto', 'direct', 'claude_code', 'antigravity', 'opencode', 'codex'] as HarnessType[]).map((mode) => (
              <button
                key={mode}
                onClick={() => setHarness(mode)}
                className={`py-1 px-2 rounded-lg text-center font-medium transition-all ${
                  harness === mode
                    ? 'bg-cyan-500 text-slate-950 shadow-sm'
                    : 'bg-slate-800/80 text-slate-300 hover:bg-slate-700'
                }`}
              >
                {mode === 'claude_code' ? 'Claude' : mode}
              </button>
            ))}
          </div>
        </div>

        {/* Streamed Thoughts & Execution Log */}
        <div className="flex-1 mt-4 bg-slate-950/80 rounded-xl p-3 border border-slate-800 font-mono text-xs text-slate-300 overflow-y-auto space-y-1">
          {thoughts.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center px-4">
              <Compass className="w-8 h-8 mb-2 opacity-40 text-cyan-400" />
              <span>Ready to assist. Set a goal to delegate or execute directly.</span>
            </div>
          ) : (
            // Chunks are streamed tokens, so they join into one continuous text
            <div className="whitespace-pre-wrap leading-relaxed">{thoughts.join('')}</div>
          )}
          <div ref={logEndRef} />
        </div>

        {/* Input & Action Control */}
        <div className="mt-3 space-y-2">
          <div className="relative">
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="E.g., Open VS Code, fix tests with Aider, and summarize diff..."
              rows={2}
              className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 resize-none"
            />
          </div>

          <div className="flex items-center space-x-2">
            {!isRunning ? (
              <button
                onClick={handleStart}
                disabled={!ws}
                className="flex-1 py-2 px-4 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed text-slate-950 font-semibold rounded-xl text-xs flex items-center justify-center space-x-1.5 transition-all shadow-md"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Execute Objective</span>
              </button>
            ) : (
              <button
                onClick={handleCancel}
                className="flex-1 py-2 px-4 bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold rounded-xl text-xs flex items-center justify-center space-x-1.5 transition-all"
              >
                <Pause className="w-3.5 h-3.5 fill-current" />
                <span>Pause Task</span>
              </button>
            )}
          </div>
        </div>

        {/* Emergency Stop Note */}
        <div className="mt-2.5 flex items-center justify-between text-[10px] text-slate-400 px-1">
          <span className="flex items-center space-x-1 text-amber-400/90">
            <ShieldAlert className="w-3 h-3" />
            <span>Emergency Kill: Hit <kbd className="bg-slate-800 px-1 rounded text-white">Esc</kbd></span>
          </span>
          <span>Dual Mode Engine</span>
        </div>
      </div>
    </div>
  );
}
