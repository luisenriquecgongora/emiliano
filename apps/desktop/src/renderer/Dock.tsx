import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, Compass, History, Plus, Send, ShieldAlert, Square, Trash2, X } from 'lucide-react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { useEngineSocket } from './engine';
import {
  CHAT_WS_URL,
  ChatMessage,
  ChatSummary,
  MODES,
  Mode,
  chatsApi,
  relativeTime,
} from './chats';

const PENDING_ID = 'pending';

// -------------------------------------------------------------
// FLOATING DOCK (chat with saved history)
// -------------------------------------------------------------
export default function Dock() {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [mode, setMode] = useState<Mode>('auto');
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const refreshChats = useCallback(() => {
    chatsApi.list().then(setChats).catch((e) => setError(String(e)));
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
        case 'done':
          updatePending((m) => ({ ...event.message, reasoning: m.reasoning, route: m.route }));
          setChats((prev) => [event.chat, ...prev.filter((c) => c.id !== event.chat.id)]);
          setBusy(false);
          break;
        case 'cancelled':
          updatePending((m) => ({ ...m, id: `stopped-${Date.now()}`, pending: false, content: `${m.content}\n\n[stopped]` }));
          setBusy(false);
          break;
        case 'error':
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
    } catch (e) {
      setError(String(e));
    }
  };

  const clearConversation = () => {
    setActiveId(null);
    setMessages([]);
    setError(null);
  };

  const newChat = () => {
    setShowHistory(false);
    clearConversation();
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
      ws.send(JSON.stringify({ type: 'send', chat_id: chatId, content, mode }));
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  const stop = () => ws?.send(JSON.stringify({ type: 'cancel' }));

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
          onToggleHistory={() => setShowHistory((open) => !open)}
          onNewChat={newChat}
          busy={busy}
        />

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

        <Composer
          draft={draft}
          onDraft={setDraft}
          mode={mode}
          onMode={setMode}
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
  busy: boolean;
  onToggleHistory: () => void;
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
    <div className="flex flex-col items-start">
      {message.route && <span className="text-[10px] text-slate-500 mb-0.5 ml-1">via {message.route}</span>}
      <div className="max-w-[92%] bg-slate-800/90 text-slate-100 text-xs rounded-2xl rounded-bl-sm px-3 py-2">
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
          <div className="whitespace-pre-wrap leading-relaxed select-text">{message.content}</div>
        )}
      </div>
    </div>
  );
}

function Composer(props: {
  draft: string;
  onDraft: (value: string) => void;
  mode: Mode;
  onMode: (mode: Mode) => void;
  busy: boolean;
  connected: boolean;
  onSend: () => void;
  onStop: () => void;
}) {
  return (
    <div className="mt-3">
      <div className="bg-slate-900 border border-slate-700 rounded-xl focus-within:border-cyan-500">
        <textarea
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
