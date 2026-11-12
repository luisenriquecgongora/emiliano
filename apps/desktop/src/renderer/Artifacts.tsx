import React, { useMemo, useState } from 'react';
import { Check, CheckSquare, ChevronDown, ChevronRight, Code, Copy, Eye, GitBranch, Layers, Sparkles } from 'lucide-react';
import { parseMessageParts, splitInlineCode } from './messageParts';
import { DiffFile, DiffLine, looksLikeUnifiedDiff, parseUnifiedDiff, toSplitRows } from './diffParse';

// -------------------------------------------------------------
// 1. MERMAID FLOWCHART PARSER & SVG RENDERER
// -------------------------------------------------------------
interface DiagramNode {
  id: string;
  label: string;
  shape: 'rect' | 'round' | 'diamond' | 'capsule';
  rank: number;
  x: number;
  y: number;
}

interface DiagramEdge {
  from: string;
  to: string;
  label?: string;
  style?: 'solid' | 'dashed' | 'thick';
}

function parseMermaidFlowchart(code: string): {
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  direction: 'TD' | 'LR';
  width: number;
  height: number;
} {
  const lines = code.split('\n').map((l) => l.trim()).filter((l) => l && !l.startsWith('%%'));
  let direction: 'TD' | 'LR' = 'TD';

  if (lines.length > 0 && /^(flowchart|graph)\s+(TD|TB|LR)/i.test(lines[0])) {
    const match = lines[0].match(/^(flowchart|graph)\s+(TD|TB|LR)/i);
    if (match && match[2].toUpperCase() === 'LR') {
      direction = 'LR';
    }
  }

  const nodeMap = new Map<string, { id: string; label: string; shape: DiagramNode['shape'] }>();
  const edges: DiagramEdge[] = [];

  const ensureNode = (id: string, explicitLabel?: string, shape: DiagramNode['shape'] = 'rect') => {
    const cleanId = id.trim();
    if (!cleanId) return cleanId;
    if (!nodeMap.has(cleanId)) {
      nodeMap.set(cleanId, {
        id: cleanId,
        label: explicitLabel ? explicitLabel.replace(/^["']|["']$/g, '') : cleanId,
        shape,
      });
    } else if (explicitLabel) {
      const existing = nodeMap.get(cleanId)!;
      existing.label = explicitLabel.replace(/^["']|["']$/g, '');
      existing.shape = shape;
    }
    return cleanId;
  };

  const parseNodeToken = (token: string): string => {
    token = token.trim();
    // Diamond: id{Label}
    let m = token.match(/^([a-zA-Z0-9_-]+)\{(.*?)\}$/);
    if (m) return ensureNode(m[1], m[2], 'diamond');
    // Capsule: id([Label])
    m = token.match(/^([a-zA-Z0-9_-]+)\(\[(.*?)\]\)$/);
    if (m) return ensureNode(m[1], m[2], 'capsule');
    // Round: id(Label)
    m = token.match(/^([a-zA-Z0-9_-]+)\((.*?)\)$/);
    if (m) return ensureNode(m[1], m[2], 'round');
    // Rect: id[Label]
    m = token.match(/^([a-zA-Z0-9_-]+)\[(.*?)\]$/);
    if (m) return ensureNode(m[1], m[2], 'rect');
    // Plain id
    m = token.match(/^([a-zA-Z0-9_-]+)$/);
    if (m) return ensureNode(m[1]);
    return token;
  };

  for (const rawLine of lines) {
    if (/^(flowchart|graph)\s+/i.test(rawLine) || /^subgraph\s+/i.test(rawLine) || rawLine === 'end') {
      continue;
    }

    // Split arrow connections: e.g. A --> B or A -->|label| B or A -- label --> B
    const arrowRegex = /(-->|-.->|==>|---|--\s*.*?\s*-->|-->\|.*?\|)/g;
    const parts = rawLine.split(arrowRegex).filter(Boolean);

    if (parts.length >= 3) {
      let currentLeft = parts[0];
      for (let i = 1; i < parts.length; i += 2) {
        const arrow = parts[i];
        const rightToken = parts[i + 1];
        if (!rightToken) break;

        const fromId = parseNodeToken(currentLeft);
        const toId = parseNodeToken(rightToken);

        let edgeLabel: string | undefined;
        let style: DiagramEdge['style'] = 'solid';

        if (arrow.includes('-.->')) style = 'dashed';
        else if (arrow.includes('==>')) style = 'thick';

        const pipeMatch = arrow.match(/-->\|(.*?)\|/);
        if (pipeMatch) {
          edgeLabel = pipeMatch[1].trim();
        } else {
          const dashMatch = arrow.match(/--\s*(.*?)\s*-->/);
          if (dashMatch) edgeLabel = dashMatch[1].trim();
        }

        if (fromId && toId) {
          edges.push({ from: fromId, to: toId, label: edgeLabel, style });
        }
        currentLeft = rightToken;
      }
    } else {
      parseNodeToken(rawLine);
    }
  }

  // Calculate topological ranks
  const inDegree = new Map<string, number>();
  const adj = new Map<string, string[]>();
  nodeMap.forEach((_, id) => {
    inDegree.set(id, 0);
    adj.set(id, []);
  });

  edges.forEach((e) => {
    if (adj.has(e.from)) adj.get(e.from)!.push(e.to);
    if (inDegree.has(e.to)) inDegree.set(e.to, (inDegree.get(e.to) || 0) + 1);
  });

  const ranks = new Map<string, number>();
  nodeMap.forEach((_, id) => ranks.set(id, 0));

  // BFS / topological relaxation
  let changed = true;
  let iterations = 0;
  while (changed && iterations < 15) {
    changed = false;
    iterations++;
    edges.forEach((e) => {
      const rFrom = ranks.get(e.from) || 0;
      const rTo = ranks.get(e.to) || 0;
      if (rTo <= rFrom) {
        ranks.set(e.to, rFrom + 1);
        changed = true;
      }
    });
  }

  // Group nodes by rank
  const rankGroups = new Map<number, string[]>();
  ranks.forEach((rank, id) => {
    if (!rankGroups.has(rank)) rankGroups.set(rank, []);
    rankGroups.get(rank)!.push(id);
  });

  const NODE_W = 110;
  const NODE_H = 36;
  const GAP_X = direction === 'TD' ? 24 : 60;
  const GAP_Y = direction === 'TD' ? 50 : 20;

  const nodePositions = new Map<string, { x: number; y: number }>();
  let maxW = 320;
  let maxH = 200;

  if (direction === 'TD') {
    const sortedRanks = Array.from(rankGroups.keys()).sort((a, b) => a - b);
    sortedRanks.forEach((rank) => {
      const ids = rankGroups.get(rank)!;
      const totalWidth = ids.length * NODE_W + (ids.length - 1) * GAP_X;
      maxW = Math.max(maxW, totalWidth + 40);
    });

    sortedRanks.forEach((rank) => {
      const ids = rankGroups.get(rank)!;
      const totalWidth = ids.length * NODE_W + (ids.length - 1) * GAP_X;
      const startX = (maxW - totalWidth) / 2;
      const y = rank * (NODE_H + GAP_Y) + 25;

      ids.forEach((id, idx) => {
        const x = startX + idx * (NODE_W + GAP_X);
        nodePositions.set(id, { x, y });
      });
      maxH = Math.max(maxH, y + NODE_H + 30);
    });
  } else {
    // LR direction
    const sortedRanks = Array.from(rankGroups.keys()).sort((a, b) => a - b);
    let currentX = 20;
    sortedRanks.forEach((rank) => {
      const ids = rankGroups.get(rank)!;
      const totalHeight = ids.length * NODE_H + (ids.length - 1) * GAP_Y;
      maxH = Math.max(maxH, totalHeight + 40);
    });

    sortedRanks.forEach((rank) => {
      const ids = rankGroups.get(rank)!;
      const totalHeight = ids.length * NODE_H + (ids.length - 1) * GAP_Y;
      const startY = (maxH - totalHeight) / 2;

      ids.forEach((id, idx) => {
        const y = startY + idx * (NODE_H + GAP_Y);
        nodePositions.set(id, { x: currentX, y });
      });
      currentX += NODE_W + GAP_X;
      maxW = Math.max(maxW, currentX + 20);
    });
  }

  const nodes: DiagramNode[] = [];
  nodeMap.forEach((meta, id) => {
    const pos = nodePositions.get(id) || { x: 20, y: 20 };
    nodes.push({
      id,
      label: meta.label,
      shape: meta.shape,
      rank: ranks.get(id) || 0,
      x: pos.x,
      y: pos.y,
    });
  });

  return { nodes, edges, direction, width: maxW, height: maxH };
}

export function MermaidDiagram({ code, title }: { code: string; title?: string }) {
  const [viewMode, setViewMode] = useState<'diagram' | 'code'>('diagram');
  const [copied, setCopied] = useState(false);

  const diagram = useMemo(() => {
    try {
      return parseMermaidFlowchart(code);
    } catch {
      return null;
    }
  }, [code]);

  const copyCode = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const NODE_W = 110;
  const NODE_H = 36;

  return (
    <div className="my-2.5 rounded-xl border border-cyan-800/60 bg-slate-950/80 overflow-hidden shadow-lg backdrop-blur-sm">
      <div className="px-3 py-2 bg-slate-900/90 border-b border-cyan-900/50 flex items-center justify-between">
        <div className="flex items-center space-x-1.5 text-cyan-300 text-[11px] font-semibold">
          <GitBranch className="w-3.5 h-3.5 text-cyan-400" />
          <span>{title || 'Architecture & Flow Diagram'}</span>
        </div>
        <div className="flex items-center space-x-1">
          <button
            onClick={() => setViewMode(viewMode === 'diagram' ? 'code' : 'diagram')}
            className="flex items-center space-x-1 px-2 py-0.5 rounded text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
          >
            {viewMode === 'diagram' ? (
              <>
                <Code className="w-3 h-3 text-cyan-400" />
                <span>Code</span>
              </>
            ) : (
              <>
                <Eye className="w-3 h-3 text-cyan-400" />
                <span>Diagram</span>
              </>
            )}
          </button>
          <button
            onClick={copyCode}
            title="Copy diagram code"
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {viewMode === 'code' || !diagram ? (
        <pre className="p-3 text-[11px] text-cyan-200/90 bg-slate-950 font-mono overflow-x-auto whitespace-pre leading-relaxed">
          {code}
        </pre>
      ) : (
        <div className="p-2 overflow-x-auto flex justify-center bg-radial-gradient">
          <svg
            width="100%"
            height={diagram.height}
            viewBox={`0 0 ${diagram.width} ${diagram.height}`}
            className="select-none max-w-full"
            style={{ minWidth: Math.min(diagram.width, 320) }}
          >
            <defs>
              <marker
                id="cyan-arrow"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 1 L 9 5 L 0 9 z" fill="#38bdf8" />
              </marker>
              <linearGradient id="nodeGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#1e293b" />
                <stop offset="100%" stopColor="#0f172a" />
              </linearGradient>
            </defs>

            {/* Edges */}
            {diagram.edges.map((edge, idx) => {
              const src = diagram.nodes.find((n) => n.id === edge.from);
              const dst = diagram.nodes.find((n) => n.id === edge.to);
              if (!src || !dst) return null;

              const isTD = diagram.direction === 'TD';
              const x1 = src.x + NODE_W / 2;
              const y1 = isTD ? src.y + NODE_H : src.y + NODE_H / 2;
              const x2 = dst.x + NODE_W / 2;
              const y2 = isTD ? dst.y : dst.y + NODE_H / 2;

              const midY = (y1 + y2) / 2;
              const midX = (x1 + x2) / 2;
              const d = isTD
                ? `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2 - 2}`
                : `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2 - 2} ${y2}`;

              return (
                <g key={idx}>
                  <path
                    d={d}
                    fill="none"
                    stroke="#38bdf8"
                    strokeWidth={edge.style === 'thick' ? '2.5' : '1.5'}
                    strokeDasharray={edge.style === 'dashed' ? '4 3' : undefined}
                    markerEnd="url(#cyan-arrow)"
                    opacity="0.85"
                  />
                  {edge.label && (
                    <g>
                      <rect
                        x={midX - (edge.label.length * 3.5 + 4)}
                        y={midY - 7}
                        width={edge.label.length * 7 + 8}
                        height={14}
                        rx="3"
                        fill="#090d16"
                        stroke="#1e293b"
                        strokeWidth="0.8"
                      />
                      <text
                        x={midX}
                        y={midY + 3}
                        textAnchor="middle"
                        fill="#7dd3fc"
                        fontSize="9"
                        fontFamily="monospace"
                      >
                        {edge.label}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}

            {/* Nodes */}
            {diagram.nodes.map((node) => {
              const rx = node.shape === 'round' || node.shape === 'capsule' ? 14 : 6;
              return (
                <g key={node.id} className="cursor-pointer group">
                  <rect
                    x={node.x}
                    y={node.y}
                    width={NODE_W}
                    height={NODE_H}
                    rx={rx}
                    fill="url(#nodeGrad)"
                    stroke="#0284c7"
                    strokeWidth="1.2"
                    className="group-hover:stroke-cyan-300 transition-all duration-200 filter drop-shadow-[0_2px_6px_rgba(2,132,199,0.3)]"
                  />
                  <text
                    x={node.x + NODE_W / 2}
                    y={node.y + NODE_H / 2 + 3.5}
                    textAnchor="middle"
                    fill="#f1f5f9"
                    fontSize="10"
                    fontWeight="500"
                    fontFamily="system-ui, sans-serif"
                    className="pointer-events-none select-none"
                  >
                    {node.label.length > 15 ? `${node.label.slice(0, 14)}…` : node.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------
// 2. INTERACTIVE PLAN CHECKLIST
// -------------------------------------------------------------
interface PlanStep {
  index: number;
  text: string;
  done: boolean;
}

export function InteractivePlan({ content, title }: { content: string; title?: string }) {
  const parsedSteps = useMemo(() => {
    const lines = content.split('\n');
    const steps: PlanStep[] = [];
    lines.forEach((line, idx) => {
      const match = line.match(/^\s*-\s*\[([ xX])\]\s+(.*)$/);
      if (match) {
        steps.push({
          index: idx,
          done: match[1].toLowerCase() === 'x',
          text: match[2].trim(),
        });
      }
    });
    return steps;
  }, [content]);

  const [completed, setCompleted] = useState<Set<number>>(() => {
    const set = new Set<number>();
    parsedSteps.forEach((s) => {
      if (s.done) set.add(s.index);
    });
    return set;
  });

  const toggleStep = (idx: number) => {
    setCompleted((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const total = parsedSteps.length;
  const count = completed.size;
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;

  return (
    <div className="my-2.5 rounded-xl border border-cyan-800/60 bg-slate-950/80 overflow-hidden shadow-lg backdrop-blur-sm">
      <div className="px-3 py-2 bg-slate-900/90 border-b border-cyan-900/50 flex items-center justify-between">
        <div className="flex items-center space-x-1.5 text-cyan-300 text-[11px] font-semibold">
          <CheckSquare className="w-3.5 h-3.5 text-cyan-400" />
          <span>{title || 'Interactive Execution Plan'}</span>
        </div>
        <div className="flex items-center space-x-2">
          <span className="text-[10px] text-cyan-400 font-mono font-semibold">
            {count}/{total} done ({pct}%)
          </span>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full h-1 bg-slate-900 overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Step List */}
      <div className="p-2 space-y-1.5">
        {parsedSteps.map((step) => {
          const isDone = completed.has(step.index);
          return (
            <div
              key={step.index}
              onClick={() => toggleStep(step.index)}
              className={`p-2 rounded-lg flex items-start space-x-2.5 cursor-pointer transition-colors ${
                isDone ? 'bg-slate-900/40 opacity-70' : 'bg-slate-900/80 hover:bg-slate-850'
              }`}
            >
              <div
                className={`w-4 h-4 rounded mt-0.5 flex items-center justify-center shrink-0 border transition-colors ${
                  isDone
                    ? 'bg-emerald-500 border-emerald-400 text-slate-950'
                    : 'border-slate-600 bg-slate-950 hover:border-cyan-400'
                }`}
              >
                {isDone && <Check className="w-3 h-3 stroke-[3]" />}
              </div>
              <span
                className={`text-xs select-text leading-relaxed ${
                  isDone ? 'line-through text-slate-400' : 'text-slate-200'
                }`}
              >
                {step.text}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// -------------------------------------------------------------
// 3. PARSED MESSAGE CONTENT COMPONENT
// -------------------------------------------------------------
function CodeBlock({ code, lang, plain = false }: { code: string; lang: string; plain?: boolean }) {
  const [copied, setCopied] = useState(false);
  // Diffs get the diff viewer: a ```diff/```patch block, or any block that holds a unified diff
  if (!plain && (lang === 'diff' || lang === 'patch' || looksLikeUnifiedDiff(code))) {
    return <DiffViewer code={code} />;
  }
  const copy = () => {
    navigator.clipboard
      ?.writeText(code)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => undefined);
  };
  return (
    <div className="my-1 rounded-lg border border-slate-700/70 bg-slate-950/90 overflow-hidden">
      <div className="px-3 py-1 flex items-center justify-between bg-slate-900/90 border-b border-slate-800 text-[10px] text-slate-400">
        <span className="font-mono">{lang || 'code'}</span>
        <button onClick={copy} className="flex items-center space-x-1 hover:text-cyan-300" title="Copy code">
          {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <pre className="px-3 py-2 overflow-x-auto text-[11px] leading-relaxed text-slate-200 select-text">
        <code className="font-mono">{code}</code>
      </pre>
    </div>
  );
}

// -------------------------------------------------------------
// 4. DIFF VIEWER (unified or side-by-side)
// -------------------------------------------------------------
const DIFF_ROW: Record<DiffLine['kind'], string> = {
  add: 'bg-emerald-950/60 text-emerald-100',
  del: 'bg-rose-950/60 text-rose-100',
  context: 'text-slate-300',
};
const DIFF_SIGN: Record<DiffLine['kind'], string> = { add: '+', del: '-', context: ' ' };

function LineNo({ n }: { n: number | null }) {
  return <span className="inline-block w-8 shrink-0 pr-1.5 text-right text-slate-600 select-none">{n ?? ''}</span>;
}

function UnifiedHunk({ lines }: { lines: DiffLine[] }) {
  return (
    <>
      {lines.map((l, i) => (
        <div key={i} className={`flex whitespace-pre ${DIFF_ROW[l.kind]}`}>
          <LineNo n={l.oldNo} />
          <LineNo n={l.newNo} />
          <span className="w-3 shrink-0 select-none opacity-70">{DIFF_SIGN[l.kind]}</span>
          <span>{l.text}</span>
        </div>
      ))}
    </>
  );
}

function SplitCell({ line, side }: { line: DiffLine | null; side: 'old' | 'new' }) {
  if (!line) return <div className="flex-1 min-w-0 bg-slate-900/40" />;
  return (
    <div className={`flex-1 min-w-0 flex whitespace-pre overflow-hidden ${DIFF_ROW[line.kind]}`}>
      <LineNo n={side === 'old' ? line.oldNo : line.newNo} />
      <span className="truncate">{line.text}</span>
    </div>
  );
}

function DiffFileView({ file, split }: { file: DiffFile; split: boolean }) {
  const [open, setOpen] = useState(true);
  const name = file.status === 'deleted' ? file.oldPath : file.newPath;
  const badge = { added: 'new', deleted: 'deleted', renamed: `from ${file.oldPath}`, modified: '' }[file.status];
  return (
    <div className="border-t border-slate-800 first:border-t-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full px-2 py-1 flex items-center justify-between text-left bg-slate-900/70 hover:bg-slate-900 text-[10px]"
      >
        <span className="flex items-center space-x-1 min-w-0">
          {open ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
          <span className="font-mono text-slate-200 truncate">{name}</span>
          {badge && <span className="text-slate-500 truncate">{badge}</span>}
        </span>
        <span className="font-mono shrink-0 ml-2">
          <span className="text-emerald-400">+{file.additions}</span>{' '}
          <span className="text-rose-400">-{file.deletions}</span>
        </span>
      </button>
      {open && (
        <div className="overflow-x-auto font-mono text-[10.5px] leading-[1.45] select-text">
          {file.hunks.map((hunk, h) => (
            <div key={h}>
              <div className="px-2 py-0.5 text-cyan-400/80 bg-cyan-950/30 whitespace-pre">{hunk.header}</div>
              {split ? (
                toSplitRows(hunk).map((row, r) => (
                  <div key={r} className="flex divide-x divide-slate-800">
                    <SplitCell line={row.left} side="old" />
                    <SplitCell line={row.right} side="new" />
                  </div>
                ))
              ) : (
                <UnifiedHunk lines={hunk.lines} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** A unified diff as files with colored lines and line numbers; falls back to plain code if it does not parse. */
export function DiffViewer({ code }: { code: string }) {
  const files = useMemo(() => parseUnifiedDiff(code), [code]);
  const [split, setSplit] = useState(false);
  const [copied, setCopied] = useState(false);
  if (files.length === 0) return <CodeBlock code={code} lang="diff" plain />;
  const additions = files.reduce((n, f) => n + f.additions, 0);
  const deletions = files.reduce((n, f) => n + f.deletions, 0);
  const copy = () => {
    navigator.clipboard
      ?.writeText(code)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => undefined);
  };
  return (
    <div className="my-1 rounded-lg border border-slate-700/70 bg-slate-950/90 overflow-hidden">
      <div className="px-3 py-1 flex items-center justify-between bg-slate-900/90 border-b border-slate-800 text-[10px] text-slate-400">
        <span className="flex items-center space-x-1.5">
          <GitBranch className="w-3 h-3 text-cyan-400" />
          <span>
            {files.length} file{files.length === 1 ? '' : 's'} <span className="text-emerald-400">+{additions}</span>{' '}
            <span className="text-rose-400">-{deletions}</span>
          </span>
        </span>
        <span className="flex items-center space-x-2">
          <button
            onClick={() => setSplit((s) => !s)}
            title={split ? 'Show as one column' : 'Show old and new side by side'}
            className="flex items-center space-x-1 hover:text-cyan-300"
          >
            <Layers className="w-3 h-3" />
            <span>{split ? 'Unified' : 'Split'}</span>
          </button>
          <button onClick={copy} className="flex items-center space-x-1 hover:text-cyan-300" title="Copy diff">
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>
        </span>
      </div>
      {files.map((file, i) => (
        <DiffFileView key={i} file={file} split={split} />
      ))}
    </div>
  );
}

function ProseWithInlineCode({ text }: { text: string }) {
  return (
    <div className="whitespace-pre-wrap leading-relaxed select-text">
      {splitInlineCode(text).map((seg, i) =>
        seg.code ? (
          <code key={i} className="px-1 py-0.5 rounded bg-slate-950/80 text-cyan-200 font-mono text-[0.92em]">
            {seg.text}
          </code>
        ) : (
          <React.Fragment key={i}>{seg.text}</React.Fragment>
        ),
      )}
    </div>
  );
}

export function ParsedMessageContent({ content }: { content: string }) {
  const parts = useMemo(() => parseMessageParts(content), [content]);

  return (
    <div className="space-y-2">
      {parts.map((part, idx) => {
        if (part.type === 'mermaid') {
          return <MermaidDiagram key={idx} code={part.content} />;
        }
        if (part.type === 'plan') {
          return <InteractivePlan key={idx} content={part.content} />;
        }
        if (part.type === 'code') {
          return <CodeBlock key={idx} code={part.content} lang={part.lang} />;
        }
        const text = part.content.trim();
        if (!text) return null;
        return <ProseWithInlineCode key={idx} text={text} />;
      })}
    </div>
  );
}
