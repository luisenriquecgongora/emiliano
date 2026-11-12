import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, Compass, Copy, Cpu, Crosshair, History, Monitor, Pin, PinOff, Plus, RefreshCw, Send, ShieldAlert, Sparkles, Square, Trash2, X } from 'lucide-react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { useEngineSocket } from './engine';
import { ParsedMessageContent } from './Artifacts';
import {
  CHAT_WS_URL,
  ChatMessage,
  ChatSummary,
  ContextMetrics,
  FIT_LABELS,
  LocalModel,
  MODES,
  Mode,
  ModelChoice,
  ModelProvider,
  ModelRecommendations,
  PermissionRequest,
  chatsApi,
  directModelGroups,
  formatGb,
  modelsApi,
  relativeTime,
} from './chats';
import { DesktopWindow, UIElement, coworkApi } from './cowork';

const PENDING_ID = 'pending';

// -------------------------------------------------------------
// FLOATING DOCK (chat with saved history)
// -------------------------------------------------------------
export default function Dock() {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [mode, setMode] = useState<Mode>('auto');
  const [model, setModel] = useState<ModelChoice>({ provider: '', model: '' });
  const [modelGroups, setModelGroups] = useState<ModelProvider[]>([]);
  const [localModels, setLocalModels] = useState<ModelRecommendations | null>(null);
  const [showModels, setShowModels] = useState(false);
  const [modelAction, setModelAction] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [pinnedWindow, setPinnedWindow] = useState<{ hwnd: number; title: string } | null>(null);
  const [showWindows, setShowWindows] = useState(false);
  const [windows, setWindows] = useState<DesktopWindow[]>([]);
  const [elements, setElements] = useState<UIElement[]>([]);
  const [showElements, setShowElements] = useState(false);
  const [loadingWindows, setLoadingWindows] = useState(false);
  const [loadingElements, setLoadingElements] = useState(false);
  const [metrics, setMetrics] = useState<ContextMetrics | null>(null);
  const [compacting, setCompacting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [permission, setPermission] = useState<PermissionRequest | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const refreshChats = useCallback(() => {
    chatsApi.list().then(setChats).catch((e) => setError(String(e)));
  }, []);

  const refreshWindows = useCallback(async () => {
    setLoadingWindows(true);
    try {
      const list = await coworkApi.listWindows();
      setWindows(list);
      const pinned = list.find((w) => w.is_pinned);
      if (pinned) {
        setPinnedWindow({ hwnd: pinned.hwnd, title: pinned.title });
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingWindows(false);
    }
  }, []);

  const handlePin = async (w: DesktopWindow) => {
    try {
      await coworkApi.pin(w.hwnd, w.title);
      setPinnedWindow({ hwnd: w.hwnd, title: w.title });
      setShowWindows(false);
      setShowElements(false);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleUnpin = async () => {
    try {
      await coworkApi.unpin();
      setPinnedWindow(null);
      setShowElements(false);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleToggleElements = async () => {
    if (!pinnedWindow) return;
    if (showElements) {
      setShowElements(false);
      return;
    }
    setLoadingElements(true);
    setShowElements(true);
    try {
      const els = await coworkApi.getElements(pinnedWindow.hwnd);
      setElements(els);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingElements(false);
    }
  };

  const handleTestClick = async (el: UIElement) => {
    try {
      const targetX = el.bounds.x + Math.floor(el.bounds.width / 2);
      const targetY = el.bounds.y + Math.floor(el.bounds.height / 2);
      await coworkApi.click(targetX, targetY);
    } catch (e) {
      setError(String(e));
    }
  };

  const refreshMetrics = useCallback((chatId: string) => {
    chatsApi.getContext(chatId).then(setMetrics).catch(() => setMetrics(null));
  }, []);

  // Updates the reply that is streaming in (the last, pending assistant message)
  const updatePending = (change: (m: ChatMessage) => ChatMessage) =>
    setMessages((prev) => prev.map((m) => (m.id === PENDING_ID ? change(m) : m)));

  const ws = useEngineSocket(
    (event) => {
      switch (event.type) {
        case 'route':
          updatePending((m) => ({ ...m, route: event.display_name }));
          break;
        case 'reasoning':
          updatePending((m) => ({ ...m, reasoning: (m.reasoning ?? '') + event.content }));
          break;
        case 'chunk':
          updatePending((m) => ({ ...m, content: m.content + event.content }));
          break;
        case 'artifact':
          updatePending((m) => ({
            ...m,
            artifacts: [...(m.artifacts ?? []), event as any],
          }));
          break;
        case 'permission_request':
          setPermission(event as PermissionRequest);
          break;
        case 'permission_closed':
          setPermission((p) => (p?.request_id === event.request_id ? null : p));
          break;
        case 'done':
          setPermission(null);
          updatePending((m) => ({ ...event.message, reasoning: m.reasoning, route: m.route }));
          setChats((prev) => [event.chat, ...prev.filter((c) => c.id !== event.chat.id)]);
          if (event.chat?.id) refreshMetrics(event.chat.id);
          setBusy(false);
          break;
        case 'cancelled':
          setPermission(null);
          updatePending((m) => ({ ...m, id: `stopped-${Date.now()}`, pending: false, content: `${m.content}\n\n[stopped]` }));
          setBusy(false);
          break;
        case 'error':
          setPermission(null);
          setMessages((prev) => prev.filter((m) => m.id !== PENDING_ID));
          setError(event.message);
          setBusy(false);
          break;
      }
    },
    refreshChats,
    CHAT_WS_URL,
  );

  const openChat = async (id: string) => {
    setShowHistory(false);
    setError(null);
    setActiveId(id);
    try {
      setMessages((await chatsApi.get(id)).messages);
      refreshMetrics(id);
    } catch (e) {
      setError(String(e));
    }
  };

  const clearConversation = () => {
    setActiveId(null);
    setMessages([]);
    setMetrics(null);
    setError(null);
  };

  const newChat = () => {
    setShowHistory(false);
    clearConversation();
  };

  const handleCompact = async () => {
    if (!activeId || compacting) return;
    setCompacting(true);
    try {
      const res = await chatsApi.compact(activeId);
      if (res.status === 'compacted') {
        await openChat(activeId);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setCompacting(false);
    }
  };

  // Deleting keeps the history panel open, so several chats can be removed in a row
  const deleteChat = async (id: string) => {
    await chatsApi.remove(id).catch((e) => setError(String(e)));
    if (id === activeId) clearConversation();
    refreshChats();
  };

  const deleteAllChats = async () => {
    await chatsApi.removeAll().catch((e) => setError(String(e)));
    clearConversation();
    refreshChats();
  };

  const send = async () => {
    const content = draft.trim();
    if (!content || !ws || busy) return;
    setError(null);
    setBusy(true);
    setDraft('');
    try {
      // A chat is created on its first message, so empty chats never pile up in history
      const chatId = activeId ?? (await chatsApi.create()).id;
      setActiveId(chatId);
      setMessages((prev) => [
        ...prev,
        { id: `user-${Date.now()}`, role: 'user', content },
        { id: PENDING_ID, role: 'assistant', content: '', pending: true },
      ]);
      ws.send(JSON.stringify({ type: 'send', chat_id: chatId, content, mode, ...(model.provider ? model : {}) }));
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  const stop = () => ws?.send(JSON.stringify({ type: 'cancel' }));

  // optionId null rejects the request
  const answerPermission = (optionId: string | null) => {
    if (!permission) return;
    ws?.send(JSON.stringify({ type: 'permission_response', request_id: permission.request_id, option_id: optionId }));
    setPermission(null);
  };

  const refreshModels = useCallback(() => {
    modelsApi
      .list()
      .then(({ models }) => setModelGroups(directModelGroups(models)))
      .catch((e) => console.error('Models:', e));
    modelsApi
      .recommendations()
      .then(setLocalModels)
      .catch((e) => console.error('Model recommendations:', e));
  }, []);

  // The models to pick from: refreshed whenever the engine (re)connects, e.g. after `ollama pull`
  useEffect(() => {
    if (ws) refreshModels();
  }, [ws, refreshModels]);

  // Load keeps a local model in memory so replies start at once; Unload frees its VRAM and RAM
  const toggleLoaded = async (m: LocalModel) => {
    setModelAction(m.name);
    try {
      await (m.loaded ? modelsApi.unload(m.name) : modelsApi.load(m.name));
    } catch (e) {
      setError(String(e));
    } finally {
      setModelAction(null);
      refreshModels();
    }
  };

  // Emergency kill switch: the desktop shell sends this when Esc is pressed anywhere
  useEffect(() => {
    if (!isTauri()) return;
    const unlisten = listen('emergency-stop', stop);
    return () => {
      unlisten.then((off) => off());
    };
  }, [ws]);

  // Only capture Esc system-wide while a reply runs, so it keeps working in other apps otherwise
  useEffect(() => {
    if (!isTauri()) return;
    invoke('set_kill_switch', { enabled: busy }).catch((e) => console.error('Kill switch:', e));
  }, [busy]);

  return (
    <div className="w-full h-full p-3 flex flex-col">
      <div className="glass-panel rounded-2xl p-4 flex-1 flex flex-col overflow-hidden relative">
        <Header
          connected={!!ws}
          historyOpen={showHistory}
          windowsOpen={showWindows}
          pinnedTitle={pinnedWindow?.title}
          busy={busy}
          onToggleHistory={() => {
            setShowHistory((open) => !open);
            setShowWindows(false);
          }}
          onToggleWindows={() => {
            setShowWindows((open) => {
              if (!open) refreshWindows();
              return !open;
            });
            setShowHistory(false);
          }}
          onNewChat={newChat}
        />

        {pinnedWindow && (
          <div className="mt-2 px-2.5 py-1.5 rounded-lg bg-cyan-950/40 border border-cyan-800/50 flex items-center justify-between text-[11px] text-cyan-300">
            <div className="flex items-center space-x-1.5 truncate">
              <Crosshair className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
              <span className="font-semibold text-white truncate max-w-[210px]">{pinnedWindow.title}</span>
              <span className="text-[10px] text-cyan-500 font-mono">HWND:{pinnedWindow.hwnd}</span>
            </div>
            <div className="flex items-center space-x-1 shrink-0">
              <button
                onClick={handleToggleElements}
                title="Inspect UI controls of this window"
                className="px-1.5 py-0.5 rounded bg-cyan-900/60 hover:bg-cyan-800 text-[10px] text-cyan-200"
              >
                {showElements ? 'Hide UI' : 'Inspect UI'}
              </button>
              <button
                onClick={handleUnpin}
                title="Unpin window"
                className="p-1 hover:text-white text-cyan-400"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          </div>
        )}

        {showWindows && (
          <WindowsPanel
            windows={windows}
            loading={loadingWindows}
            pinnedHwnd={pinnedWindow?.hwnd}
            onRefresh={refreshWindows}
            onPin={handlePin}
            onUnpin={handleUnpin}
            onClose={() => setShowWindows(false)}
          />
        )}

        {showElements && (
          <ElementsPanel
            elements={elements}
            loading={loadingElements}
            onTestClick={handleTestClick}
            onClose={() => setShowElements(false)}
          />
        )}

        {activeId && metrics && messages.length > 0 && (
          <div className="mt-2 px-2.5 py-1.5 rounded-lg bg-slate-900/60 border border-slate-800 flex items-center justify-between text-[11px]">
            <div className="flex items-center space-x-2">
              <span className="text-slate-400 font-mono text-[10px]">
                {metrics.total_tokens.toLocaleString()} / {(metrics.max_tokens / 1000).toFixed(0)}k
              </span>
              <div className="w-16 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    metrics.status === 'CRITICAL'
                      ? 'bg-rose-500'
                      : metrics.status === 'HIGH'
                        ? 'bg-amber-500'
                        : metrics.status === 'MODERATE'
                          ? 'bg-yellow-400'
                          : 'bg-cyan-400'
                  }`}
                  style={{ width: `${Math.min(100, Math.max(3, metrics.usage_percentage))}%` }}
                />
              </div>
              <span className="text-[10px] text-slate-500">{metrics.usage_percentage}%</span>
            </div>
            {messages.length >= 4 && (
              <button
                onClick={handleCompact}
                disabled={compacting || busy}
                title="Summarize older messages to free context tokens"
                className="flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 hover:text-white transition-colors disabled:opacity-40 text-[10px]"
              >
                <Sparkles className="w-3 h-3 text-cyan-400" />
                <span>{compacting ? 'Compacting…' : 'Compact'}</span>
              </button>
            )}
          </div>
        )}

        {showHistory && (
          <HistoryPanel
            chats={chats}
            activeId={activeId}
            busy={busy}
            onOpen={openChat}
            onDelete={deleteChat}
            onDeleteAll={deleteAllChats}
          />
        )}

        <div className="flex-1 mt-3 overflow-y-auto space-y-3 pr-1">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center px-6 text-xs">
              <Compass className="w-8 h-8 mb-2 opacity-40 text-cyan-400" />
              <span>Ask anything, or give Emiliano a task.</span>
            </div>
          ) : (
            messages.map((m) => <MessageBubble key={m.id} message={m} />)
          )}
          <div ref={endRef} />
        </div>

        {error && (
          <div className="mt-2 text-[11px] text-rose-300 bg-rose-950/60 border border-rose-800/60 rounded-lg px-2 py-1 flex justify-between">
            <span className="truncate">{error}</span>
            <button onClick={() => setError(null)} className="ml-2 text-rose-400 hover:text-white">
              <X className="w-3 h-3" />
            </button>
          </div>
        )}

        {permission && <PermissionCard request={permission} onAnswer={answerPermission} />}

        {showModels && (
          <ModelsPanel
            data={localModels}
            busyModel={modelAction}
            onRefresh={refreshModels}
            onToggleLoaded={toggleLoaded}
            onClose={() => setShowModels(false)}
          />
        )}

        <Composer
          draft={draft}
          onDraft={setDraft}
          mode={mode}
          onMode={setMode}
          model={model}
          modelGroups={modelGroups}
          localModels={localModels?.models ?? []}
          onModel={setModel}
          onToggleModels={() => {
            setShowModels((open) => {
              if (!open) refreshModels();
              return !open;
            });
          }}
          busy={busy}
          connected={!!ws}
          onSend={send}
          onStop={stop}
        />
      </div>
    </div>
  );
}

function Header(props: {
  connected: boolean;
  historyOpen: boolean;
  windowsOpen: boolean;
  pinnedTitle?: string;
  busy: boolean;
  onToggleHistory: () => void;
  onToggleWindows: () => void;
  onNewChat: () => void;
}) {
  const iconButton = 'text-slate-400 hover:text-white hover:bg-slate-700 rounded-md p-1 transition-colors disabled:opacity-40';
  return (
    // data-tauri-drag-region: the window is frameless, so the header moves it
    <div data-tauri-drag-region className="flex items-center justify-between pb-3 border-b border-slate-700/60 cursor-move">
      <div data-tauri-drag-region className="flex items-center space-x-2">
        <div className={`w-2.5 h-2.5 rounded-full ${props.connected ? 'bg-cyan-400' : 'bg-amber-400 animate-pulse'}`} />
        <h1 data-tauri-drag-region className="text-sm font-bold tracking-wide text-white">EMILIANO</h1>
        {!props.connected && <span className="text-[10px] text-amber-300">Starting engine…</span>}
      </div>
      <div className="flex items-center space-x-1">
        <button
          title={props.pinnedTitle ? `Pinned to: ${props.pinnedTitle}` : "Pin to target desktop window"}
          onClick={props.onToggleWindows}
          className={`${iconButton} ${props.pinnedTitle ? 'text-cyan-400 bg-cyan-950/80 border border-cyan-700/60' : props.windowsOpen ? 'bg-slate-700 text-white' : ''}`}
        >
          {props.pinnedTitle ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
        </button>
        <button title="Chat history" onClick={props.onToggleHistory} className={`${iconButton} ${props.historyOpen ? 'bg-slate-700 text-white' : ''}`}>
          <History className="w-4 h-4" />
        </button>
        <button title="New chat" onClick={props.onNewChat} disabled={props.busy} className={iconButton}>
          <Plus className="w-4 h-4" />
        </button>
        {isTauri() && (
          <button title="Quit Emiliano" onClick={() => getCurrentWindow().close()} className={iconButton}>
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}

function WindowsPanel(props: {
  windows: DesktopWindow[];
  loading: boolean;
  pinnedHwnd?: number;
  onRefresh: () => void;
  onPin: (w: DesktopWindow) => void;
  onUnpin: () => void;
  onClose: () => void;
}) {
  return (
    <div className="absolute inset-x-3 top-14 bottom-3 z-10 bg-slate-950 border border-slate-700 rounded-xl flex flex-col overflow-hidden shadow-2xl">
      <div className="px-3 py-2 text-[11px] font-semibold text-slate-400 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-1.5">
          <Monitor className="w-3.5 h-3.5 text-cyan-400" />
          <span>Desktop Windows</span>
        </div>
        <div className="flex items-center space-x-2">
          {props.pinnedHwnd && (
            <button
              onClick={props.onUnpin}
              className="text-[10px] text-rose-400 hover:text-rose-300 transition-colors"
            >
              Unpin
            </button>
          )}
          <button
            onClick={props.onRefresh}
            disabled={props.loading}
            title="Refresh windows"
            className="text-slate-400 hover:text-white"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${props.loading ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={props.onClose} className="text-slate-400 hover:text-white">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-slate-800/60">
        {props.windows.length === 0 && (
          <div className="p-4 text-xs text-slate-500 text-center">
            {props.loading ? 'Scanning desktop windows…' : 'No desktop windows detected.'}
          </div>
        )}
        {props.windows.map((win) => {
          const isPinned = props.pinnedHwnd === win.hwnd;
          return (
            <div
              key={win.hwnd}
              onClick={() => props.onPin(win)}
              className={`p-2.5 flex items-center justify-between cursor-pointer hover:bg-slate-900 transition-colors ${
                isPinned ? 'bg-cyan-950/40 border-l-2 border-cyan-400' : ''
              }`}
            >
              <div className="min-w-0 pr-2">
                <div className="text-xs text-slate-200 truncate font-medium">{win.title}</div>
                <div className="text-[10px] text-slate-500 font-mono">
                  HWND: {win.hwnd} • {win.bounds.width}×{win.bounds.height}
                </div>
              </div>
              <span
                className={`text-[10px] px-2 py-0.5 rounded font-mono shrink-0 ${
                  isPinned
                    ? 'bg-cyan-400 text-slate-950 font-bold'
                    : 'bg-slate-800 text-slate-400 hover:text-cyan-300'
                }`}
              >
                {isPinned ? 'PINNED' : 'PIN'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ElementsPanel(props: {
  elements: UIElement[];
  loading: boolean;
  onTestClick: (el: UIElement) => void;
  onClose: () => void;
}) {
  return (
    <div className="absolute inset-x-3 top-24 bottom-3 z-10 bg-slate-950/95 backdrop-blur-md border border-cyan-800/60 rounded-xl flex flex-col overflow-hidden shadow-2xl">
      <div className="px-3 py-2 text-[11px] font-semibold text-cyan-400 border-b border-slate-800 flex items-center justify-between bg-cyan-950/30">
        <div className="flex items-center space-x-1.5">
          <Crosshair className="w-3.5 h-3.5 text-cyan-400" />
          <span>
            Detected UI Elements ({props.elements.some((el) => el.source === 'uia') ? 'UI Automation' : 'Win32'})
          </span>
        </div>
        <button onClick={props.onClose} className="text-slate-400 hover:text-white">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto divide-y divide-slate-800/60">
        {props.elements.length === 0 && (
          <div className="p-4 text-xs text-slate-500 text-center">
            {props.loading ? 'Extracting UI accessibility tree…' : 'No child controls detected.'}
          </div>
        )}
        {props.elements.map((el, i) => (
          <div key={i} className="p-2 flex items-center justify-between hover:bg-slate-900/80 transition-colors">
            <div className="min-w-0 pr-2">
              <div className="flex items-center space-x-1.5">
                <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-cyan-300 font-mono">
                  {el.role}
                </span>
                <span className="text-xs text-slate-200 truncate">{el.name}</span>
              </div>
              <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                {el.class} • ({el.bounds.x}, {el.bounds.y}) {el.bounds.width}×{el.bounds.height}
              </div>
            </div>
            {el.action === 'click' && (
              <button
                onClick={() => props.onTestClick(el)}
                className="px-2 py-0.5 text-[10px] rounded bg-cyan-900/60 hover:bg-cyan-700 text-cyan-200 shrink-0 font-mono"
              >
                Safe Click
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function HistoryPanel(props: {
  chats: ChatSummary[];
  activeId: string | null;
  busy: boolean;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onDeleteAll: () => void;
}) {
  // Deleting asks once inline ("Delete?"), since a deleted chat cannot be restored
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <div className="absolute inset-x-3 top-14 bottom-3 z-10 bg-slate-950 border border-slate-700 rounded-xl flex flex-col overflow-hidden">
      <div className="px-3 py-2 text-[11px] font-semibold text-slate-400 border-b border-slate-800">Chat history</div>
      <div className="flex-1 overflow-y-auto">
        {props.chats.length === 0 && <div className="p-4 text-xs text-slate-500 text-center">No saved chats yet.</div>}
        {props.chats.map((chat) => (
          <div
            key={chat.id}
            className={`group flex items-center px-3 py-2 text-xs border-b border-slate-900 ${
              chat.id === props.activeId ? 'bg-slate-800/70' : 'hover:bg-slate-800/40'
            }`}
          >
            {confirming === chat.id ? (
              <>
                <span className="flex-1 text-rose-300 truncate">Delete “{chat.title}”?</span>
                <button onClick={() => { props.onDelete(chat.id); setConfirming(null); }} className="ml-2 px-2 py-0.5 rounded bg-rose-600 hover:bg-rose-500 text-white">Delete</button>
                <button onClick={() => setConfirming(null)} className="ml-1 px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200">Cancel</button>
              </>
            ) : (
              <>
                <button
                  disabled={props.busy}
                  onClick={() => props.onOpen(chat.id)}
                  className="flex-1 text-left truncate text-slate-200 disabled:cursor-not-allowed"
                  title={chat.title}
                >
                  {chat.title}
                </button>
                <span className="ml-2 text-[10px] text-slate-500 shrink-0">{relativeTime(chat.updated_at)}</span>
                <button
                  title="Delete chat"
                  disabled={props.busy && chat.id === props.activeId}
                  onClick={() => setConfirming(chat.id)}
                  className="ml-2 text-slate-500 hover:text-rose-400 opacity-60 group-hover:opacity-100 disabled:opacity-20"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </>
            )}
          </div>
        ))}
      </div>
      {props.chats.length > 0 && (
        <div className="px-3 py-2 border-t border-slate-800 text-[11px]">
          {confirming === 'all' ? (
            <span className="flex items-center justify-between text-rose-300">
              Delete all {props.chats.length} chats?
              <span>
                <button disabled={props.busy} onClick={() => { props.onDeleteAll(); setConfirming(null); }} className="px-2 py-0.5 rounded bg-rose-600 hover:bg-rose-500 text-white disabled:opacity-40">Delete all</button>
                <button onClick={() => setConfirming(null)} className="ml-1 px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200">Cancel</button>
              </span>
            </span>
          ) : (
            <button onClick={() => setConfirming('all')} className="text-slate-500 hover:text-rose-400">Clear all history</button>
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] bg-cyan-600/90 text-white text-xs rounded-2xl rounded-br-sm px-3 py-2 whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    );
  }
  const waiting = message.pending && !message.content;
  return (
    <div className="flex flex-col items-start w-full">
      {message.route && <span className="text-[10px] text-slate-500 mb-0.5 ml-1">via {message.route}</span>}
      <div className="w-full max-w-[96%] bg-slate-800/90 text-slate-100 text-xs rounded-2xl rounded-bl-sm px-3 py-2">
        {message.reasoning && (
          <details className="mb-1.5 text-slate-400">
            <summary className="cursor-pointer select-none text-[10px] uppercase tracking-wide">
              {message.pending && !message.content ? 'Thinking…' : 'Thought process'}
            </summary>
            <div className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed max-h-40 overflow-y-auto">{message.reasoning}</div>
          </details>
        )}
        {waiting && !message.reasoning ? (
          <span className="text-slate-400 animate-pulse">Working…</span>
        ) : (
          <ParsedMessageContent content={message.content} />
        )}
      </div>
    </div>
  );
}

function PermissionCard({ request, onAnswer }: { request: PermissionRequest; onAnswer: (optionId: string | null) => void }) {
  const allows = request.options.filter((o) => o.kind.startsWith('allow'));
  const rejects = request.options.filter((o) => o.kind.startsWith('reject'));
  return (
    <div className="mt-2 rounded-lg border border-amber-700/60 bg-amber-950/50 px-2.5 py-2 text-[11px]">
      <div className="flex items-center space-x-1.5 text-amber-300">
        <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
        <span className="font-semibold">Agent asks permission</span>
        <span className="text-[10px] font-mono text-amber-500">{request.kind}</span>
      </div>
      <div className="mt-1 text-slate-100 break-words">{request.title}</div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {allows.map((o) => (
          <button
            key={o.optionId}
            onClick={() => onAnswer(o.optionId)}
            className="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold"
          >
            {o.name}
          </button>
        ))}
        {(rejects.length ? rejects : [null]).map((o) => (
          <button
            key={o?.optionId ?? 'reject'}
            onClick={() => onAnswer(o ? o.optionId : null)}
            className="px-2 py-0.5 rounded bg-slate-700 hover:bg-rose-700 text-slate-100"
          >
            {o?.name ?? 'Deny'}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Local models rated for this machine, with Load/Unload, plus models worth downloading. */
function ModelsPanel(props: {
  data: ModelRecommendations | null;
  busyModel: string | null;
  onRefresh: () => void;
  onToggleLoaded: (m: LocalModel) => void;
  onClose: () => void;
}) {
  const hw = props.data?.hardware;
  return (
    <div className="absolute inset-x-3 top-14 bottom-28 z-10 bg-slate-950 border border-slate-700 rounded-xl flex flex-col overflow-hidden shadow-2xl">
      <div className="px-3 py-2 text-[11px] font-semibold text-slate-400 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-1.5">
          <Cpu className="w-3.5 h-3.5 text-cyan-400" />
          <span>Local models</span>
        </div>
        <div className="flex items-center space-x-2">
          <button onClick={props.onRefresh} title="Refresh" className="text-slate-400 hover:text-white">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button onClick={props.onClose} className="text-slate-400 hover:text-white">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {!props.data ? (
          <div className="p-4 text-xs text-slate-500 text-center">Checking your hardware and models…</div>
        ) : (
          <>
            <div className="px-3 py-2 text-[10px] text-slate-400 border-b border-slate-800/60">
              {hw?.gpuName ? `${hw.gpuName}, ${formatGb(hw.vramBytes)} VRAM` : 'No NVIDIA GPU found'} ·{' '}
              {formatGb(hw?.ramBytes ?? 0)} RAM
            </div>
            {props.data.models.length === 0 && (
              <div className="p-3 text-xs text-slate-500">No local models installed.</div>
            )}
            <div className="divide-y divide-slate-800/60">
              {props.data.models.map((m) => (
                <div key={m.name} className="p-2.5 flex items-center justify-between">
                  <div className="min-w-0 pr-2">
                    <div className="text-xs text-slate-200 truncate font-medium">
                      {FIT_LABELS[m.fit].icon} {m.name}
                      {m.recommended && (
                        <span className="ml-1.5 text-[9px] text-cyan-300 bg-cyan-950 rounded px-1">recommended</span>
                      )}
                    </div>
                    <div className="text-[10px] text-slate-500">
                      {formatGb(m.sizeBytes)} · {FIT_LABELS[m.fit].text} ·{' '}
                      {m.tools === null ? 'tool support unknown' : m.tools ? 'uses file tools' : 'no tool support'}
                      {m.loaded && <span className="text-emerald-400"> · in memory ({formatGb(m.vramBytes)} on GPU)</span>}
                    </div>
                  </div>
                  <button
                    onClick={() => props.onToggleLoaded(m)}
                    disabled={props.busyModel !== null || (!m.loaded && m.fit === 'too_big')}
                    title={m.loaded ? 'Free the memory this model holds' : 'Load into memory now so replies start at once'}
                    className={`shrink-0 px-2 py-0.5 rounded text-[10px] disabled:opacity-40 ${
                      m.loaded ? 'bg-slate-800 hover:bg-slate-700 text-amber-300' : 'bg-cyan-900/60 hover:bg-cyan-800 text-cyan-200'
                    }`}
                  >
                    {props.busyModel === m.name ? '…' : m.loaded ? 'Unload' : 'Load'}
                  </button>
                </div>
              ))}
            </div>
            {props.data.suggestions.length > 0 && (
              <>
                <div className="px-3 pt-3 pb-1 text-[10px] font-semibold text-slate-400">Suggested downloads for this PC</div>
                <div className="divide-y divide-slate-800/60">
                  {props.data.suggestions.map((s) => (
                    <div key={s.name} className="px-3 py-2 flex items-center justify-between">
                      <div className="min-w-0 pr-2">
                        <div className="text-xs text-slate-200 truncate">
                          {FIT_LABELS[s.fit].icon} {s.name} <span className="text-[10px] text-slate-500">~{s.sizeGb} GB</span>
                        </div>
                        <div className="text-[10px] text-slate-500 truncate">{s.note}</div>
                      </div>
                      <button
                        onClick={() => navigator.clipboard?.writeText(s.pull).catch(() => undefined)}
                        title={`Copy "${s.pull}", then run it in a terminal`}
                        className="shrink-0 flex items-center space-x-1 px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-[10px] text-slate-300 font-mono"
                      >
                        <Copy className="w-3 h-3" />
                        <span>pull</span>
                      </button>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** Pins replies to one model; "Default model" lets the mode dropdown decide. Value is "provider|model". */
function ModelPicker(props: {
  value: ModelChoice;
  groups: ModelProvider[];
  localModels: LocalModel[];
  onChange: (model: ModelChoice) => void;
}) {
  // Local models get their hardware rating, e.g. "✅ qwen3.5:2b (recommended)"
  const label = (provider: string, name: string) => {
    const local = provider === 'ollama' ? props.localModels.find((m) => m.name === name) : undefined;
    if (!local) return name;
    return `${FIT_LABELS[local.fit].icon} ${name}${local.recommended ? ' (recommended)' : ''}`;
  };
  const current = props.value.provider ? `${props.value.provider}|${props.value.model}` : '';
  return (
    <label className="relative flex items-center text-[11px] text-slate-300 ml-1 min-w-0">
      <select
        value={current}
        onChange={(e) => {
          const [provider, ...rest] = e.target.value.split('|');
          props.onChange({ provider, model: rest.join('|') });
        }}
        title="Model that answers: a picked model replaces the mode on the left"
        className="appearance-none bg-slate-800 hover:bg-slate-700 rounded-lg pl-2 pr-6 py-1 focus:outline-none cursor-pointer max-w-[160px] truncate"
      >
        <option value="">Default model</option>
        {props.groups.map((g) => (
          <optgroup key={g.name} label={g.displayName}>
            {g.availableModels.map((m) => (
              <option key={`${g.name}|${m}`} value={`${g.name}|${m}`}>{label(g.name, m)}</option>
            ))}
          </optgroup>
        ))}
      </select>
      <ChevronDown className="w-3 h-3 absolute right-1.5 pointer-events-none text-slate-400" />
    </label>
  );
}

function Composer(props: {
  draft: string;
  onDraft: (value: string) => void;
  mode: Mode;
  onMode: (mode: Mode) => void;
  model: ModelChoice;
  modelGroups: ModelProvider[];
  localModels: LocalModel[];
  onModel: (model: ModelChoice) => void;
  onToggleModels: () => void;
  busy: boolean;
  connected: boolean;
  onSend: () => void;
  onStop: () => void;
}) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  // The summon shortcut (Ctrl+Shift+Space by default) brings the dock up ready to type
  useEffect(() => {
    if (!isTauri()) return;
    const unlisten = listen('summon', () => inputRef.current?.focus());
    return () => {
      unlisten.then((off) => off());
    };
  }, []);
  return (
    <div className="mt-3">
      <div className="bg-slate-900 border border-slate-700 rounded-xl focus-within:border-cyan-500">
        <textarea
          ref={inputRef}
          value={props.draft}
          onChange={(e) => props.onDraft(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter adds a line
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              props.onSend();
            }
          }}
          placeholder="Message Emiliano…"
          rows={2}
          className="w-full bg-transparent px-3 pt-2 text-xs text-slate-100 placeholder-slate-500 focus:outline-none resize-none select-text"
        />
        <div className="flex items-center justify-between px-2 pb-2">
          <label className="relative flex items-center text-[11px] text-slate-300">
            <select
              value={props.mode}
              onChange={(e) => props.onMode(e.target.value as Mode)}
              title="Who answers: Auto picks for you"
              className="appearance-none bg-slate-800 hover:bg-slate-700 rounded-lg pl-2 pr-6 py-1 focus:outline-none cursor-pointer"
            >
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
            <ChevronDown className="w-3 h-3 absolute right-1.5 pointer-events-none text-slate-400" />
          </label>
          <ModelPicker
            value={props.model}
            groups={props.modelGroups}
            localModels={props.localModels}
            onChange={props.onModel}
          />
          <button
            onClick={props.onToggleModels}
            title="Local models: hardware fit, load and unload, suggested downloads"
            className="p-1 mr-auto ml-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white"
          >
            <Cpu className="w-3.5 h-3.5" />
          </button>
          {props.busy ? (
            <button onClick={props.onStop} title="Stop (Esc)" className="flex items-center space-x-1 bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold rounded-lg px-3 py-1 text-[11px]">
              <Square className="w-3 h-3 fill-current" />
              <span>Stop</span>
            </button>
          ) : (
            <button
              onClick={props.onSend}
              disabled={!props.connected || !props.draft.trim()}
              title="Send (Enter)"
              className="flex items-center space-x-1 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-950 font-semibold rounded-lg px-3 py-1 text-[11px]"
            >
              <Send className="w-3 h-3" />
              <span>Send</span>
            </button>
          )}
        </div>
      </div>
      <div className="mt-1.5 flex items-center text-[10px] text-slate-500 px-1">
        <ShieldAlert className="w-3 h-3 mr-1 text-amber-400/80" />
        <span>
          Stop anytime with <kbd className="bg-slate-800 px-1 rounded text-slate-200">Esc</kbd>
        </span>
      </div>
    </div>
  );
}
