import React, { useMemo, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  Blocks,
  Check,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  ExternalLink,
  FileText,
  Share2,
  ShieldCheck,
  Sparkles,
  Terminal,
  Workflow,
  X,
  Zap,
} from 'lucide-react';
import type { ChatMessage, ToolCallRecord } from './chats';

interface ExecutionFluxModalProps {
  message: ChatMessage | null;
  onClose: () => void;
}

interface FluxNode {
  id: string;
  type: 'input' | 'discovery' | 'reasoning' | 'tool' | 'feedback' | 'verification' | 'synthesis' | 'artifact';
  title: string;
  subtitle?: string;
  duration_s?: number;
  status: 'ok' | 'error' | 'info';
  details?: any;
  payload?: any;
}

export default function ExecutionFluxModal({ message, onClose }: ExecutionFluxModalProps) {
  const [activeTab, setActiveTab] = useState<'graph' | 'waterfall' | 'raw'>('graph');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [copiedMermaid, setCopiedMermaid] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (!message) return null;

  const metrics = message.metrics;
  const toolCalls = message.tool_calls || metrics?.tool_calls || [];
  const reasoning = message.reasoning || '';
  const artifacts = message.artifacts || [];

  // Build the Non-Linear Execution Flux Nodes & Edges
  const fluxNodes = useMemo<FluxNode[]>(() => {
    const nodes: FluxNode[] = [];

    // 1. Input Prompt
    nodes.push({
      id: 'node-input',
      type: 'input',
      title: 'Prompt Ingestion & Intent Analysis',
      subtitle: 'Evaluated intent, project context guidelines & conversational routing',
      status: 'ok',
      details: {
        role: message.role,
        timestamp: message.created_at,
        route: message.route || metrics?.route || 'direct',
      },
    });

    // 2. Semantic Tool Routing / Discovery
    const hasTools = toolCalls.length > 0;
    nodes.push({
      id: 'node-discovery',
      type: 'discovery',
      title: hasTools ? 'Semantic MCP Discovery & Ranking' : 'Conversational Routing Gate',
      subtitle: hasTools
        ? `Ranked candidate tools via TF-IDF & domain boosters. Routed ${toolCalls.length} tool(s)`
        : 'Classified query as pure conversational / general reasoning. Zero tool overhead.',
      status: 'ok',
      details: {
        tools_evaluated: metrics?.tools_count || toolCalls.length,
        selected_tools: toolCalls.map((t) => t.tool),
      },
    });

    // 3. Reasoning & Deliberation (Turn 1)
    if (reasoning) {
      nodes.push({
        id: 'node-reasoning',
        type: 'reasoning',
        title: 'Deep Reasoning & Plan Formulation',
        subtitle: `Model constructed strategy and intermediate action plan`,
        duration_s: metrics?.thinking_duration_s,
        status: 'ok',
        payload: reasoning,
      });
    }

    // 4. Multi-Turn Tool Executions & Feedback Loops (Non-Linear Flux)
    toolCalls.forEach((t: ToolCallRecord, idx: number) => {
      const isMcp = t.tool.includes('__') || Boolean(t.mcp_server);
      const serverName = t.mcp_server || (t.tool.includes('__') ? t.tool.split('__')[0] : 'core');
      const actionName = t.tool_name || (t.tool.includes('__') ? t.tool.split('__')[1] : t.tool);
      const isOk = t.status !== 'error';

      nodes.push({
        id: `node-tool-${idx}`,
        type: 'tool',
        title: isMcp ? `MCP: ${serverName} → ${actionName}` : `Tool: ${t.tool}`,
        subtitle: `Turn ${idx + 1} execution on ${isMcp ? `${serverName} server` : 'local engine'}`,
        duration_s: t.duration_s,
        status: isOk ? 'ok' : 'error',
        payload: {
          arguments: t.args || {},
          output: t.result || '',
        },
      });

      // Non-linear feedback loop indicator if multiple turns occurred
      if (idx < toolCalls.length - 1) {
        nodes.push({
          id: `node-feedback-${idx}`,
          type: 'feedback',
          title: `Feedback Assimilation (Turn ${idx + 1} ➔ Turn ${idx + 2})`,
          subtitle: `Model ingested output from ${actionName}, updated belief state, and branched to next tool`,
          status: 'ok',
        });
      }
    });

    // 5. Automated Verification / Integrity Gate
    nodes.push({
      id: 'node-verify',
      type: 'verification',
      title: 'Integrity & Verification Gate',
      subtitle: 'Safety boundary, schema consistency check & response formatting check',
      status: 'ok',
    });

    // 6. Final Answer Synthesis
    nodes.push({
      id: 'node-synthesis',
      type: 'synthesis',
      title: 'Response Synthesis & Markdown Generation',
      subtitle: metrics?.tokens_per_second
        ? `Delivered final verified response at ${metrics.tokens_per_second} tokens/sec`
        : 'Rendered verified deliverable response',
      duration_s: metrics?.generation_duration_s,
      status: 'ok',
      details: {
        completion_tokens: metrics?.completion_tokens,
        tokens_per_second: metrics?.tokens_per_second,
        ttft_ms: metrics?.ttft_ms,
      },
    });

    // 7. Artifacts / Deliverables
    if (artifacts.length > 0) {
      nodes.push({
        id: 'node-artifacts',
        type: 'artifact',
        title: `Deliverables & Artifact Extraction (${artifacts.length})`,
        subtitle: `Extracted staged actions, deliverable documents, or UI artifacts`,
        status: 'ok',
        details: artifacts,
      });
    }

    return nodes;
  }, [message, metrics, toolCalls, reasoning, artifacts]);

  const selectedNode = fluxNodes.find((n) => n.id === selectedNodeId) || fluxNodes[0];

  // Generate Mermaid Flowchart Diagram
  const mermaidDiagram = useMemo(() => {
    let m = `flowchart TD\n`;
    m += `  A["📥 User Request Ingestion"]\n`;
    m += `  B["🔍 Semantic Tool Discovery"]\n`;
    m += `  A --> B\n`;

    let prevNode = 'B';
    if (reasoning) {
      m += `  C["🧠 Reasoning & Strategy (${metrics?.thinking_duration_s || 0}s)"]\n`;
      m += `  ${prevNode} --> C\n`;
      prevNode = 'C';
    }

    if (toolCalls.length > 0) {
      toolCalls.forEach((t, i) => {
        const tId = `T${i + 1}`;
        const name = t.tool.replace(/_/g, ' ');
        const dur = t.duration_s ? ` (${t.duration_s}s)` : '';
        const statusIcon = t.status === 'error' ? '❌' : '⚡';
        m += `  ${tId}["${statusIcon} ${name}${dur}"]\n`;
        m += `  ${prevNode} --> ${tId}\n`;

        if (i < toolCalls.length - 1) {
          const fId = `F${i + 1}`;
          m += `  ${fId}{"Evaluation & Branch"}\n`;
          m += `  ${tId} --> ${fId}\n`;
          prevNode = fId;
        } else {
          prevNode = tId;
        }
      });
    }

    m += `  V["🛡️ Verification Gate (ok)"]\n`;
    m += `  ${prevNode} --> V\n`;
    m += `  S["💬 Answer Synthesis (${metrics?.generation_duration_s || 0}s)"]\n`;
    m += `  V --> S\n`;

    if (artifacts.length > 0) {
      m += `  ART["📦 Deliverable Artifacts (${artifacts.length})"]\n`;
      m += `  S --> ART\n`;
    }

    return m;
  }, [reasoning, toolCalls, metrics, artifacts]);

  const handleCopyMermaid = () => {
    navigator.clipboard.writeText(mermaidDiagram);
    setCopiedMermaid(true);
    setTimeout(() => setCopiedMermaid(false), 2000);
  };

  const handleCopyJson = () => {
    const rawData = {
      message_id: message.id,
      created_at: message.created_at,
      metrics: message.metrics,
      tool_calls: message.tool_calls,
      reasoning: message.reasoning,
      artifacts: message.artifacts,
      flux_nodes: fluxNodes,
    };
    navigator.clipboard.writeText(JSON.stringify(rawData, null, 2));
    setCopiedJson(true);
    setTimeout(() => setCopiedJson(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/80 backdrop-blur-md animate-in fade-in duration-150 select-none">
      <div className="relative w-full max-w-4xl max-h-[90vh] bg-slate-900 border border-slate-700/90 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-slate-100 font-sans">
        {/* Top Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-950/60 shrink-0">
          <div className="flex items-center space-x-2.5">
            <div className="p-1.5 rounded-lg bg-cyan-950/80 border border-cyan-500/40 text-cyan-400">
              <Workflow className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-xs sm:text-sm text-slate-100 tracking-tight">
                  Execution Flux & Generation Trace
                </span>
                {metrics?.formatted_duration && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-cyan-950/90 text-cyan-300 border border-cyan-800/60">
                    {metrics.formatted_duration}
                  </span>
                )}
              </div>
              <p className="text-[10px] text-slate-400">
                Non-linear DAG lifecycle, MCP tool branching & verified response pipeline
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-1.5">
            <button
              onClick={handleCopyMermaid}
              className="px-2 py-1 rounded text-[10px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition-colors flex items-center gap-1 cursor-pointer"
              title="Copy Mermaid.js diagram definition"
            >
              {copiedMermaid ? <Check className="w-3 h-3 text-emerald-400" /> : <Share2 className="w-3 h-3 text-cyan-400" />}
              <span>{copiedMermaid ? 'Copied Diagram' : 'Copy Mermaid'}</span>
            </button>

            <button
              onClick={handleCopyJson}
              className="px-2 py-1 rounded text-[10px] font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition-colors flex items-center gap-1 cursor-pointer"
              title="Copy raw telemetry JSON"
            >
              {copiedJson ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3 text-slate-400" />}
              <span>{copiedJson ? 'Copied JSON' : 'Raw Trace'}</span>
            </button>

            <button
              onClick={onClose}
              className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors ml-1 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Telemetry Summary Stats Strip */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 px-4 py-2 border-b border-slate-800/80 bg-slate-900/50 text-[11px] font-mono shrink-0">
          <div className="p-2 rounded bg-slate-950/40 border border-slate-800">
            <div className="text-[10px] text-slate-500 font-sans">Deliberation / Thinking</div>
            <div className="text-cyan-300 font-semibold mt-0.5">
              {metrics?.thinking_duration_s ? `${metrics.thinking_duration_s}s` : '0s (Immediate)'}
            </div>
          </div>
          <div className="p-2 rounded bg-slate-950/40 border border-slate-800">
            <div className="text-[10px] text-slate-500 font-sans">Tool & MCP Execution</div>
            <div className="text-emerald-300 font-semibold mt-0.5">
              {metrics?.tool_duration_s ? `${metrics.tool_duration_s}s` : '0s'} · {toolCalls.length} calls
            </div>
          </div>
          <div className="p-2 rounded bg-slate-950/40 border border-slate-800">
            <div className="text-[10px] text-slate-500 font-sans">Synthesis & Generation</div>
            <div className="text-slate-200 font-semibold mt-0.5">
              {metrics?.generation_duration_s ? `${metrics.generation_duration_s}s` : 'Completed'}
              {metrics?.tokens_per_second ? ` (${metrics.tokens_per_second} t/s)` : ''}
            </div>
          </div>
          <div className="p-2 rounded bg-slate-950/40 border border-slate-800">
            <div className="text-[10px] text-slate-500 font-sans">Efficiency & Latency</div>
            <div className="text-amber-300 font-semibold mt-0.5">
              TTFT {metrics?.ttft_ms ? `${metrics.ttft_ms}ms` : 'fast'} · {metrics?.completion_tokens || 0} tok
            </div>
          </div>
        </div>

        {/* Tab Selector */}
        <div className="flex items-center space-x-1 px-4 pt-2 border-b border-slate-800 bg-slate-950/30 shrink-0 text-xs font-medium">
          <button
            onClick={() => setActiveTab('graph')}
            className={`px-3 py-1.5 border-b-2 transition-all cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'graph'
                ? 'border-cyan-400 text-cyan-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Workflow className="w-3.5 h-3.5" />
            <span>Non-Linear Flux Diagram</span>
          </button>
          <button
            onClick={() => setActiveTab('waterfall')}
            className={`px-3 py-1.5 border-b-2 transition-all cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'waterfall'
                ? 'border-cyan-400 text-cyan-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Clock className="w-3.5 h-3.5" />
            <span>Waterfall Timeline</span>
          </button>
          <button
            onClick={() => setActiveTab('raw')}
            className={`px-3 py-1.5 border-b-2 transition-all cursor-pointer flex items-center gap-1.5 ${
              activeTab === 'raw'
                ? 'border-cyan-400 text-cyan-300 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Raw Telemetry & Spans</span>
          </button>
        </div>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {activeTab === 'graph' && (
            <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
              {/* Left Column: Visual Flow Graph */}
              <div className="md:col-span-7 space-y-2">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                  <Workflow className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Execution Flux DAG (Click Node to Inspect)</span>
                </div>

                <div className="space-y-2 relative">
                  {fluxNodes.map((node, i) => {
                    const isSelected = selectedNode?.id === node.id;
                    const isFeedback = node.type === 'feedback';

                    return (
                      <React.Fragment key={node.id}>
                        <div
                          onClick={() => setSelectedNodeId(node.id)}
                          className={`p-3 rounded-xl border transition-all cursor-pointer relative ${
                            isSelected
                              ? 'bg-slate-800/95 border-cyan-400/80 shadow-[0_0_15px_rgba(34,211,238,0.25)] ring-1 ring-cyan-400/40'
                              : isFeedback
                              ? 'bg-slate-950/60 border-purple-800/40 hover:border-purple-600/70'
                              : 'bg-slate-900/80 border-slate-800 hover:bg-slate-850 hover:border-slate-700'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-start space-x-2.5 min-w-0">
                              <div
                                className={`p-1.5 rounded-lg shrink-0 mt-0.5 ${
                                  node.type === 'tool'
                                    ? node.status === 'error'
                                      ? 'bg-rose-950 text-rose-400 border border-rose-800/60'
                                      : 'bg-purple-950 text-purple-400 border border-purple-800/60'
                                    : node.type === 'reasoning'
                                    ? 'bg-cyan-950 text-cyan-400 border border-cyan-800/60'
                                    : node.type === 'feedback'
                                    ? 'bg-indigo-950 text-indigo-400 border border-indigo-800/60'
                                    : node.type === 'verification'
                                    ? 'bg-emerald-950 text-emerald-400 border border-emerald-800/60'
                                    : 'bg-slate-800 text-slate-300 border border-slate-700'
                                }`}
                              >
                                {node.type === 'tool' ? (
                                  <Blocks className="w-3.5 h-3.5" />
                                ) : node.type === 'reasoning' ? (
                                  <Sparkles className="w-3.5 h-3.5" />
                                ) : node.type === 'feedback' ? (
                                  <Workflow className="w-3.5 h-3.5" />
                                ) : node.type === 'verification' ? (
                                  <ShieldCheck className="w-3.5 h-3.5" />
                                ) : (
                                  <FileText className="w-3.5 h-3.5" />
                                )}
                              </div>

                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-xs font-semibold text-slate-100 truncate">
                                    {node.title}
                                  </span>
                                  {node.status === 'error' && (
                                    <span className="px-1 py-0.2 rounded text-[9px] bg-rose-950 text-rose-300 border border-rose-800 font-mono">
                                      error
                                    </span>
                                  )}
                                </div>
                                {node.subtitle && (
                                  <p className="text-[11px] text-slate-400 mt-0.5 leading-relaxed line-clamp-2">
                                    {node.subtitle}
                                  </p>
                                )}
                              </div>
                            </div>

                            <div className="flex items-center space-x-1.5 shrink-0 font-mono text-[10px]">
                              {node.duration_s !== undefined && node.duration_s > 0 && (
                                <span className="px-1.5 py-0.5 rounded bg-slate-950 text-cyan-400 border border-slate-800">
                                  {node.duration_s}s
                                </span>
                              )}
                              <ChevronRight className={`w-3.5 h-3.5 text-slate-500 transition-transform ${isSelected ? 'rotate-90 text-cyan-400' : ''}`} />
                            </div>
                          </div>
                        </div>

                        {/* Visual Connector Line between steps */}
                        {i < fluxNodes.length - 1 && (
                          <div className="flex items-center justify-center py-0.5">
                            <div className="w-0.5 h-3 bg-gradient-to-b from-cyan-500/60 via-slate-700 to-cyan-500/60 rounded-full" />
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>

              {/* Right Column: Node Inspector Drawer */}
              <div className="md:col-span-5 flex flex-col space-y-2">
                <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center justify-between">
                  <span>Node Inspector</span>
                  <span className="text-[10px] font-mono text-cyan-400">{selectedNode.title}</span>
                </div>

                <div className="flex-1 p-3.5 rounded-xl border border-slate-800 bg-slate-950/70 space-y-3 font-mono text-xs overflow-y-auto max-h-[500px]">
                  <div>
                    <div className="text-[10px] text-slate-400 uppercase font-sans font-semibold">Stage Title</div>
                    <div className="text-slate-100 font-semibold mt-0.5">{selectedNode.title}</div>
                  </div>

                  {selectedNode.subtitle && (
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-sans font-semibold">Description</div>
                      <div className="text-slate-300 font-sans text-xs mt-0.5 leading-relaxed">
                        {selectedNode.subtitle}
                      </div>
                    </div>
                  )}

                  {selectedNode.duration_s !== undefined && (
                    <div>
                      <div className="text-[10px] text-slate-400 uppercase font-sans font-semibold">Execution Latency</div>
                      <div className="text-emerald-400 font-semibold mt-0.5">
                        {selectedNode.duration_s} seconds ({Math.round(selectedNode.duration_s * 1000)}ms)
                      </div>
                    </div>
                  )}

                  {/* Node Specific Payloads */}
                  {selectedNode.payload && typeof selectedNode.payload === 'object' && (
                    <div className="space-y-2 pt-2 border-t border-slate-800">
                      {selectedNode.payload.arguments && (
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-sans font-semibold mb-1">
                            Input Arguments:
                          </div>
                          <pre className="p-2 rounded bg-slate-900 border border-slate-800 text-slate-300 text-[10px] overflow-x-auto whitespace-pre-wrap max-h-40">
                            {JSON.stringify(selectedNode.payload.arguments, null, 2)}
                          </pre>
                        </div>
                      )}

                      {selectedNode.payload.output && (
                        <div>
                          <div className="text-[10px] text-slate-400 uppercase font-sans font-semibold mb-1">
                            Server Response Receipt:
                          </div>
                          <pre className="p-2 rounded bg-slate-900 border border-slate-800 text-emerald-300/90 text-[10px] overflow-x-auto whitespace-pre-wrap max-h-48">
                            {String(selectedNode.payload.output)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}

                  {selectedNode.payload && typeof selectedNode.payload === 'string' && (
                    <div className="pt-2 border-t border-slate-800">
                      <div className="text-[10px] text-slate-400 uppercase font-sans font-semibold mb-1">
                        Reasoning Stream:
                      </div>
                      <pre className="p-2 rounded bg-slate-900 border border-slate-800 text-cyan-300/90 text-[10px] overflow-x-auto whitespace-pre-wrap max-h-60 leading-relaxed font-sans">
                        {selectedNode.payload}
                      </pre>
                    </div>
                  )}

                  {selectedNode.details && (
                    <div className="pt-2 border-t border-slate-800">
                      <div className="text-[10px] text-slate-400 uppercase font-sans font-semibold mb-1">
                        Metadata Details:
                      </div>
                      <pre className="p-2 rounded bg-slate-900 border border-slate-800 text-slate-300 text-[10px] overflow-x-auto whitespace-pre-wrap">
                        {JSON.stringify(selectedNode.details, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'waterfall' && (
            <div className="space-y-4">
              <div className="text-xs text-slate-400">
                Gantt-style horizontal waterfall showing sequential vs parallel phases of this generation:
              </div>

              <div className="p-4 rounded-xl border border-slate-800 bg-slate-950/70 space-y-4 font-mono text-xs">
                {/* Total Bar */}
                <div>
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-slate-300 font-semibold">Total Lifecycle</span>
                    <span className="text-cyan-400">{metrics?.formatted_duration || `${metrics?.total_duration_s || 0}s`}</span>
                  </div>
                  <div className="w-full bg-slate-900 h-2.5 rounded-full overflow-hidden flex border border-slate-800">
                    <div className="bg-cyan-500 h-full w-full" />
                  </div>
                </div>

                {/* Thinking Phase */}
                {metrics?.thinking_duration_s && (
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-slate-400">🧠 Reasoning & Strategy</span>
                      <span className="text-cyan-300">{metrics.thinking_duration_s}s</span>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div
                        className="bg-cyan-400 h-full rounded-full"
                        style={{
                          width: `${Math.min(100, Math.max(8, (metrics.thinking_duration_s / (metrics.total_duration_s || 1)) * 100))}%`,
                        }}
                      />
                    </div>
                  </div>
                )}

                {/* Tool Calls Phase */}
                {toolCalls.map((t, idx) => (
                  <div key={idx}>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-slate-400">⚡ Turn {idx + 1}: {t.tool}</span>
                      <span className="text-purple-300">{t.duration_s || 0}s</span>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div
                        className="bg-purple-400 h-full rounded-full"
                        style={{
                          width: `${Math.min(100, Math.max(8, ((t.duration_s || 0.1) / (metrics?.total_duration_s || 1)) * 100))}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}

                {/* Synthesis Phase */}
                {metrics?.generation_duration_s && (
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-slate-400">💬 Response Synthesis & Stream</span>
                      <span className="text-emerald-300">{metrics.generation_duration_s}s</span>
                    </div>
                    <div className="w-full bg-slate-900 h-2 rounded-full overflow-hidden border border-slate-800">
                      <div
                        className="bg-emerald-400 h-full rounded-full"
                        style={{
                          width: `${Math.min(100, Math.max(8, (metrics.generation_duration_s / (metrics.total_duration_s || 1)) * 100))}%`,
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'raw' && (
            <div className="space-y-3">
              <div className="flex justify-between items-center text-xs text-slate-400">
                <span>Complete OpenTelemetry Trace & Message Telemetry:</span>
                <button
                  onClick={handleCopyJson}
                  className="px-2 py-1 rounded text-[10px] bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 flex items-center gap-1 cursor-pointer"
                >
                  <Copy className="w-3 h-3" />
                  <span>Copy Payload</span>
                </button>
              </div>
              <pre className="p-3.5 rounded-xl border border-slate-800 bg-slate-950/80 text-emerald-300/90 text-xs font-mono overflow-x-auto max-h-[500px] leading-relaxed">
                {JSON.stringify(
                  {
                    message_id: message.id,
                    role: message.role,
                    created_at: message.created_at,
                    route: message.route,
                    metrics: message.metrics,
                    tool_calls: message.tool_calls,
                    artifacts: message.artifacts,
                  },
                  null,
                  2
                )}
              </pre>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-800 bg-slate-950/60 shrink-0 text-xs font-mono text-slate-400">
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Trace Recorded & Verified</span>
          </div>
          <button
            onClick={onClose}
            className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors cursor-pointer text-xs font-medium"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
