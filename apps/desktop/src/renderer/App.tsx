import React, { useState } from 'react';
import type { HUDHighlightMessage } from '@emiliano/protocol';
import Dock from './Dock';
import { isOverlayWindow, useEngineSocket } from './engine';

export default function App() {
  if (isOverlayWindow()) {
    return <HUDOverlayView />;
  }

  return <Dock />;
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
