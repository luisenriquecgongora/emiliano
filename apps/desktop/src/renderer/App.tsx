import React, { useEffect, useRef, useState } from 'react';
import type { HUDHighlightMessage } from '@emiliano/protocol';
import Dock from './Dock';
import { isOverlayWindow, useEngineSocket } from './engine';
import { toOverlayRect } from './hudGeometry';

export default function App() {
  if (isOverlayWindow()) {
    return <HUDOverlayView />;
  }

  return <Dock />;
}

// -------------------------------------------------------------
// 1. HUD OVERLAY VIEW (Fullscreen Transparent Screen Layer)
// -------------------------------------------------------------
// The engine sends HUD_HIGHLIGHT right before Cowork clicks or types into an element, so the
// person can see what is about to happen; HUD_CLEAR when the run ends.
function HUDOverlayView() {
  const [highlight, setHighlight] = useState<HUDHighlightMessage['payload'] | null>(null);
  const clearTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelTimer = () => {
    if (clearTimer.current) clearTimeout(clearTimer.current);
    clearTimer.current = null;
  };
  useEffect(() => cancelTimer, []);

  useEngineSocket((msg) => {
    if (msg.type === 'HUD_HIGHLIGHT') {
      // A new target replaces the old one; the old timer must not clear it early.
      cancelTimer();
      setHighlight(msg.payload);
      clearTimer.current = setTimeout(() => setHighlight(null), msg.payload.durationMs || 2500);
    } else if (msg.type === 'HUD_CLEAR') {
      cancelTimer();
      setHighlight(null);
    }
  });

  if (!highlight) return null;

  const { bounds, name, action } = highlight.element;
  const rect = toOverlayRect(bounds, window.devicePixelRatio);

  return (
    <div className="w-screen h-screen pointer-events-none relative overflow-hidden">
      {/* Target Bounding Box */}
      <div
        className="absolute border-2 border-cyan-400 bg-cyan-400/20 rounded shadow-[0_0_15px_rgba(34,211,238,0.8)] transition-all duration-300 animate-pulse"
        style={{ left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px` }}
      >
        <div
          className={`absolute ${rect.labelBelow ? 'top-full mt-1' : '-top-7'} left-0 bg-slate-900/90 text-cyan-300 text-xs px-2 py-0.5 rounded border border-cyan-500/40 flex items-center space-x-1 whitespace-nowrap`}
          title={highlight.reasoning}
        >
          <span className="font-semibold">{action.toUpperCase()}</span>
          <span>•</span>
          <span>{name}</span>
        </div>
      </div>
    </div>
  );
}
