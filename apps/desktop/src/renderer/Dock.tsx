import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  AudioWaveform,
  Blocks,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Circle,
  CircleDot,
  Code,
  Code2,
  Columns,
  Compass,
  Copy,
  Cpu,
  Crosshair,
  Database,
  Download,
  Eye,
  FileText,
  FolderGit2,
  Globe,
  History,
  Layers,
  Maximize2,
  Menu,
  MessageSquare,
  Mic,
  MicOff,
  Minimize2,
  Monitor,
  PanelLeft,
  PanelLeftClose,
  Pin,
  PinOff,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
  SlidersHorizontal,
  Smartphone,
  Sparkles,
  Square,
  Tablet,
  Trash2,
  User,
  Wrench,
  X,
  Zap,
} from 'lucide-react';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { getCurrentWindow, PhysicalSize } from '@tauri-apps/api/window';
import { useEngineSocket } from './engine';
import { ParsedMessageContent } from './Artifacts';
import {
  CHAT_WS_URL,
  ENGINE_HTTP_URL,
  ChatMessage,
  ChatSummary,
  DownloadStatus,
  ContextMetrics,
  FIT_LABELS,
  LocalModel,
  MODES,
  Mode,
  ModelChoice,
  ModelProvider,
  ModelRecommendations,
  PermissionRequest,
  ProjectItem,
  ArtifactItem,
  projectsApi,
  artifactsApi,
  ServiceConnection,
  SkillItem,
  chatsApi,
  connectionsApi,
  directModelGroups,
  formatGb,
  modelsApi,
  relativeTime,
  skillsApi,
} from './chats';
import { DesktopWindow, UIElement, coworkApi } from './cowork';

const PENDING_ID = 'pending';

export type ResizeDirection =
  | 'East'
  | 'North'
  | 'NorthEast'
  | 'NorthWest'
  | 'South'
  | 'SouthEast'
  | 'SouthWest'
  | 'West';

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
  const [connections, setConnections] = useState<ServiceConnection[]>([]);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [connectNote, setConnectNote] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
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
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarTab, setSidebarTab] = useState<'chats' | 'projects' | 'artifacts' | 'skills' | 'connects'>('chats');
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [loadingSkills, setLoadingSkills] = useState(false);
  const [projects, setProjects] = useState<ProjectItem[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [previewArtifact, setPreviewArtifact] = useState<ArtifactItem | null>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [showContextDetails, setShowContextDetails] = useState(false);
  const [browserStatus, setBrowserStatus] = useState<{ connected: boolean; extension_info: any }>({
    connected: false,
    extension_info: {},
  });
  const [loadingBrowser, setLoadingBrowser] = useState(false);

  const refreshBrowserStatus = useCallback(async () => {
    setLoadingBrowser(true);
    try {
      const st = await coworkApi.getBrowserStatus();
      setBrowserStatus(st);
    } catch {
      setBrowserStatus({ connected: false, extension_info: {} });
    } finally {
      setLoadingBrowser(false);
    }
  }, []);

  // Poll browser companion status every 3.5s so the HUD always reflects real-time Chrome connection
  useEffect(() => {
    refreshBrowserStatus();
    const interval = setInterval(refreshBrowserStatus, 3500);
    return () => clearInterval(interval);
  }, [refreshBrowserStatus]);

  const handleOpenBrowserSetup = useCallback(() => {
    setSidebarOpen(true);
    setSidebarTab('skills');
  }, []);

  const [currentWidth, setCurrentWidth] = useState<number>(() => {
    try {
      return window.innerWidth || 640;
    } catch {
      return 640;
    }
  });

  useEffect(() => {
    let rafId: number | null = null;
    let lastW = window.innerWidth;

    const onResize = () => {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        const w = window.innerWidth;
        // Only trigger full React re-render when crossing layout breakpoints or significant delta
        if (
          Math.abs(w - lastW) >= 16 ||
          (lastW < 480 && w >= 480) ||
          (lastW >= 480 && w < 480) ||
          (lastW < 550 && w >= 550) ||
          (lastW >= 550 && w < 550)
        ) {
          lastW = w;
          setCurrentWidth(w);
        }
        rafId = null;
      });
    };

    window.addEventListener('resize', onResize);
    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  const refreshChats = useCallback(() => {
    chatsApi.list().then(setChats).catch((e) => setError(String(e)));
  }, []);

  const refreshSkills = useCallback(async () => {
    setLoadingSkills(true);
    try {
      const data = await skillsApi.list();
      setSkills(data.skills || []);
    } catch (e) {
      console.error('Failed to load skills:', e);
    } finally {
      setLoadingSkills(false);
    }
  }, []);

  const refreshProjects = useCallback(async () => {
    setLoadingProjects(true);
    try {
      const list = await projectsApi.list();
      setProjects(list);
      // SOTA Context Isolation: Do not force-bind to list[0].
      // Keep activeProjectId as null (General / Global workspace) unless explicitly picked by user.
    } catch (e) {
      console.error('Failed to load projects:', e);
    } finally {
      setLoadingProjects(false);
    }
  }, [activeProjectId]);

  const refreshArtifacts = useCallback(async () => {
    setLoadingArtifacts(true);
    try {
      const list = await artifactsApi.list();
      setArtifacts(list);
    } catch (e) {
      console.error('Failed to load artifacts:', e);
    } finally {
      setLoadingArtifacts(false);
    }
  }, []);

  useEffect(() => {
    refreshSkills();
    refreshChats();
    refreshProjects();
    refreshArtifacts();
  }, [refreshSkills, refreshChats, refreshProjects, refreshArtifacts]);

  const toggleSidebar = useCallback(async () => {
    setSidebarOpen((prev) => {
      const next = !prev;
      if (next) {
        refreshSkills();
        refreshChats();
        refreshProjects();
        refreshArtifacts();
        if (window.innerWidth < 480) {
          coworkApi.resizeHud(940).catch(() => {});
        }
      }
      return next;
    });
    setShowWindows(false);
  }, [refreshSkills, refreshChats, refreshProjects, refreshArtifacts]);

  const openChatsSidebar = useCallback(() => {
    setSidebarTab('chats');
    setSidebarOpen(true);
    refreshChats();
    refreshProjects();
    refreshArtifacts();
    if (window.innerWidth < 480) {
      coworkApi.resizeHud(940).catch(() => {});
    }
    setShowWindows(false);
  }, [refreshChats, refreshProjects, refreshArtifacts]);

  const cycleSizePreset = useCallback(async () => {
    const w = window.innerWidth;
    let target = 640;
    if (w < 350) target = 640;
    else if (w < 550) target = 940;
    else target = 420;
    try {
      await coworkApi.resizeHud(target);
    } catch (e) {
      console.error('Failed to resize HUD:', e);
    }
  }, []);

  const handleStartResize = (e: React.MouseEvent, direction: ResizeDirection = 'West') => {
    e.preventDefault();
    e.stopPropagation();

    if (isTauri()) {
      setIsResizing(true);
      getCurrentWindow()
        .startResizeDragging(direction)
        .catch((err) => {
          console.warn('[Resize] Native startResizeDragging failed, using dynamic drag fallback:', err);
          startDynamicDrag(e, direction);
        })
        .finally(() => {
          setIsResizing(false);
        });
    } else {
      startDynamicDrag(e, direction);
    }
  };

  const startDynamicDrag = (e: React.MouseEvent, direction: ResizeDirection) => {
    setIsResizing(true);
    const startX = e.screenX;
    const startY = e.screenY;
    const startW = window.innerWidth;
    const startH = window.innerHeight;
    let lastW = startW;
    let lastH = startH;
    let animFrame: number | null = null;

    const onMouseMove = (ev: MouseEvent) => {
      const deltaX = ev.screenX - startX;
      const deltaY = ev.screenY - startY;

      let newW = startW;
      let newH = startH;

      if (direction.includes('East')) {
        newW = Math.max(360, Math.min(2400, startW + deltaX));
      } else if (direction.includes('West')) {
        newW = Math.max(360, Math.min(2400, startW - deltaX));
      }

      if (direction.includes('South')) {
        newH = Math.max(420, Math.min(1800, startH + deltaY));
      } else if (direction.includes('North')) {
        newH = Math.max(420, Math.min(1800, startH - deltaY));
      }

      if (animFrame === null) {
        animFrame = requestAnimationFrame(() => {
          animFrame = null;
          if (Math.abs(newW - lastW) >= 4 || Math.abs(newH - lastH) >= 4) {
            lastW = newW;
            lastH = newH;
            coworkApi.resizeHud(newW, newH, direction).catch(() => {});
          }
        });
      }
    };

    const onMouseUp = () => {
      setIsResizing(false);
      if (animFrame !== null) {
        cancelAnimationFrame(animFrame);
        animFrame = null;
      }
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  };

  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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
          updatePending((m) => {
            let newContent = m.content + event.content;
            let newReasoning = m.reasoning ?? '';

            if (newContent.includes('<think>')) {
              const startIdx = newContent.indexOf('<think>');
              const endIdx = newContent.indexOf('</think>');
              if (endIdx !== -1) {
                const thinkText = newContent.slice(startIdx + 7, endIdx);
                newReasoning = (newReasoning ? newReasoning + '\n' : '') + thinkText.trim();
                newContent = newContent.slice(0, startIdx) + newContent.slice(endIdx + 8);
              } else if (startIdx !== -1) {
                const thinkText = newContent.slice(startIdx + 7);
                newReasoning = thinkText;
                newContent = newContent.slice(0, startIdx);
              }
            }

            return { ...m, content: newContent, reasoning: newReasoning || undefined };
          });
          break;
        case 'artifact':
          refreshArtifacts();
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
          refreshArtifacts();
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
    () => {
      setBusy(false);
      setPermission(null);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === PENDING_ID
            ? { ...m, pending: false, content: m.content ? `${m.content}\n\n[Connection reset]` : '[Connection reset]' }
            : m,
        ),
      );
    },
  );

  const openChat = async (id: string) => {
    setError(null);
    setActiveId(id);
    if (currentWidth < 480) {
      setSidebarOpen(false);
    }
    try {
      setMessages((await chatsApi.get(id)).messages);
      refreshMetrics(id);
    } catch (e) {
      setError(String(e));
    }
  };

  const initialChatLoadedRef = useRef(false);

  // Auto-load most recent active chat on initial load if none is selected
  useEffect(() => {
    if (initialChatLoadedRef.current) return;
    if (chats.length > 0) {
      initialChatLoadedRef.current = true;
      if (!activeId) {
        openChat(chats[0].id);
      }
    }
  }, [chats]);

  const clearConversation = () => {
    setActiveId(null);
    setMessages([]);
    setMetrics(null);
    setError(null);
    setBusy(false);
    setDraft('');
  };

  const newChat = () => {
    clearConversation();
    if (currentWidth < 480) {
      setSidebarOpen(false);
    }
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

  const handleClearActiveChat = async () => {
    if (!activeId) return;
    try {
      await chatsApi.clear(activeId);
      await openChat(activeId);
    } catch (e) {
      setError(String(e));
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

  const send = async (explicitContent?: string) => {
    const content = (explicitContent || draft).trim();
    if (!content || !ws || busy) return;
    setError(null);
    setBusy(true);
    setDraft('');
    try {
      // A chat is created on its first message, associated with the active project if set
      const chatId = activeId ?? (await chatsApi.create(undefined, activeProjectId || undefined)).id;
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
    connectionsApi
      .list()
      .then(({ connections }) => setConnections(connections))
      .catch((e) => console.error('Connections:', e));
  }, []);

  // Connect opens the service's sign-in in the browser; the engine waits for the approval (up to 5 minutes)
  const toggleConnection = async (c: ServiceConnection) => {
    setConnecting(c.service);
    setConnectNote(c.connected ? null : `Approve the connection in your browser, then come back here.`);
    try {
      if (c.connected) {
        await connectionsApi.disconnect(c.service);
        setConnectNote(`${c.title} disconnected.`);
      } else {
        const r = await connectionsApi.connect(c.service);
        setConnectNote(
          r.ok
            ? `${c.title} connected: ${r.tools} tools available to the models.`
            : `${c.title} connected, but its tools did not load: ${r.error}`,
        );
      }
    } catch (e) {
      setConnectNote(null);
      setError(String(e));
    } finally {
      setConnecting(null);
      refreshModels();
    }
  };

  // The models to pick from: refreshed whenever the engine (re)connects, e.g. after `ollama pull`
  useEffect(() => {
    if (ws) refreshModels();
  }, [ws, refreshModels]);

  // Load keeps a local model in memory so replies start at once; Unload frees its VRAM and RAM
  const toggleLoaded = async (m: LocalModel) => {
    setModelAction(m.name);
    // Instant optimistic update so the button flips immediately without waiting on network
    setLocalModels((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        models: prev.models.map((item) =>
          item.name === m.name ? { ...item, loaded: !m.loaded } : item
        ),
      };
    });
    try {
      await (m.loaded ? modelsApi.unload(m.name) : modelsApi.load(m.name));
    } catch (e) {
      setError(String(e));
    } finally {
      setModelAction(null);
      refreshModels();
    }
  };

  const unloadAllLoaded = async () => {
    setModelAction('all');
    setLocalModels((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        models: prev.models.map((item) => ({ ...item, loaded: false })),
      };
    });
    try {
      await modelsApi.unloadAll();
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

  const handleQuickAction = async (promptText: string) => {
    if (!ws || busy) return;
    setError(null);
    setBusy(true);
    setDraft('');
    try {
      const chatId = activeId ?? (await chatsApi.create()).id;
      setActiveId(chatId);
      setMessages((prev) => [
        ...prev,
        { id: `user-${Date.now()}`, role: 'user', content: promptText },
        { id: PENDING_ID, role: 'assistant', content: '', pending: true },
      ]);
      ws.send(JSON.stringify({ type: 'send', chat_id: chatId, content: promptText, mode, ...(model.provider ? model : {}) }));
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  return (
    <div className="w-full h-full p-2.5 flex flex-col relative select-none">
      {/* ========================================================================= */}
      {/* 8-Direction Frameless Window Border Drag Handles (Claude Cowork Style)    */}
      {/* ========================================================================= */}
      {/* 1. Left Border (West) */}
      <div
        className="absolute left-0 top-3 bottom-3 w-2.5 cursor-ew-resize hover:bg-cyan-500/20 active:bg-cyan-500/50 transition-colors z-50 flex items-center justify-center group"
        title="Drag left border to resize horizontally"
        onMouseDown={(e) => handleStartResize(e, 'West')}
      >
        <div className="w-0.5 h-10 rounded-full bg-slate-600/30 group-hover:bg-cyan-400 group-hover:scale-y-125 transition-all" />
      </div>

      {/* 2. Right Border (East) */}
      <div
        className="absolute right-0 top-3 bottom-3 w-2.5 cursor-ew-resize hover:bg-cyan-500/20 active:bg-cyan-500/50 transition-colors z-50 flex items-center justify-center group"
        title="Drag right border to resize horizontally"
        onMouseDown={(e) => handleStartResize(e, 'East')}
      >
        <div className="w-0.5 h-10 rounded-full bg-slate-600/30 group-hover:bg-cyan-400 group-hover:scale-y-125 transition-all" />
      </div>

      {/* 3. Top Border (North) */}
      <div
        className="absolute top-0 left-3 right-3 h-2.5 cursor-ns-resize hover:bg-cyan-500/20 active:bg-cyan-500/50 transition-colors z-50 flex items-center justify-center group"
        title="Drag top border to resize vertically"
        onMouseDown={(e) => handleStartResize(e, 'North')}
      >
        <div className="h-0.5 w-10 rounded-full bg-slate-600/30 group-hover:bg-cyan-400 group-hover:scale-x-125 transition-all" />
      </div>

      {/* 4. Bottom Border (South) */}
      <div
        className="absolute bottom-0 left-3 right-3 h-2.5 cursor-ns-resize hover:bg-cyan-500/20 active:bg-cyan-500/50 transition-colors z-50 flex items-center justify-center group"
        title="Drag bottom border to resize vertically"
        onMouseDown={(e) => handleStartResize(e, 'South')}
      >
        <div className="h-0.5 w-10 rounded-full bg-slate-600/30 group-hover:bg-cyan-400 group-hover:scale-x-125 transition-all" />
      </div>

      {/* 5. Top-Left Corner (NorthWest) */}
      <div
        className="absolute top-0 left-0 w-3.5 h-3.5 cursor-nwse-resize hover:bg-cyan-400/40 active:bg-cyan-400 rounded-tl-xl transition-colors z-50"
        title="Drag corner to resize diagonally"
        onMouseDown={(e) => handleStartResize(e, 'NorthWest')}
      />

      {/* 6. Top-Right Corner (NorthEast) */}
      <div
        className="absolute top-0 right-0 w-3.5 h-3.5 cursor-nesw-resize hover:bg-cyan-400/40 active:bg-cyan-400 rounded-tr-xl transition-colors z-50"
        title="Drag corner to resize diagonally"
        onMouseDown={(e) => handleStartResize(e, 'NorthEast')}
      />

      {/* 7. Bottom-Left Corner (SouthWest) */}
      <div
        className="absolute bottom-0 left-0 w-3.5 h-3.5 cursor-nesw-resize hover:bg-cyan-400/40 active:bg-cyan-400 rounded-bl-xl transition-colors z-50"
        title="Drag corner to resize diagonally"
        onMouseDown={(e) => handleStartResize(e, 'SouthWest')}
      />

      {/* 8. Bottom-Right Corner (SouthEast) */}
      <div
        className="absolute bottom-0 right-0 w-3.5 h-3.5 cursor-nwse-resize hover:bg-cyan-400/40 active:bg-cyan-400 rounded-br-xl transition-colors z-50"
        title="Drag corner to resize diagonally"
        onMouseDown={(e) => handleStartResize(e, 'SouthEast')}
      />

      <div
        className={`glass-panel rounded-2xl p-4 flex-1 flex flex-col overflow-hidden relative ${
          isResizing ? 'pointer-events-none select-none' : ''
        }`}
      >
        <Header
          connected={!!ws}
          browserStatus={browserStatus}
          historyOpen={sidebarOpen && sidebarTab === 'chats'}
          windowsOpen={showWindows}
          sidebarOpen={sidebarOpen}
          currentWidth={currentWidth}
          pinnedTitle={pinnedWindow?.title}
          busy={busy}
          onToggleSidebar={toggleSidebar}
          onToggleHistory={openChatsSidebar}
          onToggleWindows={() => {
            setShowWindows((open) => {
              if (!open) refreshWindows();
              return !open;
            });
          }}
          onCycleSize={cycleSizePreset}
          onNewChat={newChat}
          onOpenBrowserSetup={handleOpenBrowserSetup}
        />

        {activeProjectId && (
          <div className="mt-2 px-2.5 py-1 rounded-lg bg-indigo-950/40 border border-indigo-800/50 flex items-center justify-between text-[11px] text-indigo-300">
            <div className="flex items-center space-x-1.5 truncate">
              <FolderGit2 className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
              <span className="text-[10px] text-indigo-400 uppercase font-semibold">Scope:</span>
              <span className="font-medium text-white truncate max-w-[210px]">
                {projects.find((p) => p.id === activeProjectId)?.name || activeProjectId}
              </span>
            </div>
            <button
              onClick={() => setActiveProjectId(null)}
              title="Detach project and return to General Scope"
              className="px-1.5 py-0.5 rounded bg-indigo-900/60 hover:bg-indigo-800 text-[10px] text-indigo-200 flex items-center space-x-1 cursor-pointer"
            >
              <span>General</span>
              <X className="w-3 h-3 ml-0.5" />
            </button>
          </div>
        )}

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

        {/* Clear, unmissable banner when the Chrome Companion Extension is disconnected */}
        {!browserStatus.connected && (pinnedWindow?.title?.toLowerCase().includes('chrome') || sidebarTab === 'skills') && (
          <div className="mt-2 px-2.5 py-1.5 rounded-lg bg-rose-950/80 border border-rose-700/80 flex items-center justify-between text-[11px] text-rose-200 shadow-md">
            <div className="flex items-center space-x-2 truncate">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 animate-pulse" />
              <div className="truncate">
                <span className="font-semibold text-rose-100">Chrome Extension Offline:</span>{' '}
                <span className="text-rose-300">Background DOM automation & receipts paused.</span>
              </div>
            </div>
            <button
              onClick={handleOpenBrowserSetup}
              className="px-2 py-0.5 rounded bg-rose-900 hover:bg-rose-800 text-[10px] text-white font-medium shrink-0 ml-2 border border-rose-600/60 shadow-xs"
            >
              Setup Guide
            </button>
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

        {/* Overlay FixedSidebar when window is compact (< 480px CSS) */}
        {sidebarOpen && currentWidth < 480 && (
          <FixedSidebar
            chats={chats}
            activeId={activeId}
            busy={busy}
            activeTab={sidebarTab}
            onTabChange={setSidebarTab}
            onOpenChat={openChat}
            onDeleteChat={deleteChat}
            onNewChat={newChat}
            skills={skills}
            loadingSkills={loadingSkills}
            projects={projects}
            loadingProjects={loadingProjects}
            activeProjectId={activeProjectId}
            onSelectProject={setActiveProjectId}
            onRefreshProjects={refreshProjects}
            artifacts={artifacts}
            loadingArtifacts={loadingArtifacts}
            onPreviewArtifact={setPreviewArtifact}
            onRefreshArtifacts={refreshArtifacts}
            connections={connections}
            connecting={connecting}
            connectNote={connectNote}
            onRefreshSkills={refreshSkills}
            onRefreshChats={refreshChats}
            onToggleConnection={toggleConnection}
            onActionClick={handleQuickAction}
            onClose={() => setSidebarOpen(false)}
            isOverlay={true}
            windows={windows}
            loadingWindows={loadingWindows}
            pinnedWindow={pinnedWindow}
            onPin={handlePin}
            onUnpin={handleUnpin}
            onInspectElements={handleToggleElements}
            onRefreshWindows={refreshWindows}
            browserStatus={browserStatus}
            loadingBrowser={loadingBrowser}
            onRefreshBrowserStatus={refreshBrowserStatus}
            onDeleteAllChats={deleteAllChats}
          />
        )}

        {activeId && metrics && messages.length > 0 && (
          <>
            <div className="mt-2 px-2.5 py-1.5 rounded-lg bg-slate-900/60 border border-slate-800 flex items-center justify-between text-[11px]">
              <div
                onClick={() => setShowContextDetails((prev) => !prev)}
                className="flex items-center space-x-2 cursor-pointer hover:bg-slate-800/50 px-1.5 py-0.5 rounded transition-colors select-none"
                title="Click to toggle Context Window Diagnostics & Token Breakdown"
              >
                <span className="text-[10px] text-slate-400 font-mono flex items-center space-x-1">
                  <span className="text-slate-500 font-sans">Chat Context:</span>
                  <span>{metrics.total_tokens.toLocaleString()} / {(metrics.max_tokens / 1000).toFixed(0)}k</span>
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
                <span className="text-[10px] text-slate-500 font-mono">{metrics.usage_percentage}%</span>
                <ChevronDown className={`w-3 h-3 text-slate-500 transition-transform ${showContextDetails ? 'rotate-180 text-cyan-400' : ''}`} />
              </div>
              <div className="flex items-center space-x-1.5">
                {messages.length >= 4 && (
                  <button
                    onClick={handleCompact}
                    disabled={compacting || busy}
                    title="Summarize older messages to free context tokens (Partial Flush)"
                    className="flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 hover:text-white transition-colors disabled:opacity-40 text-[10px]"
                  >
                    <Sparkles className="w-3 h-3 text-cyan-400" />
                    <span>{compacting ? 'Compacting…' : 'Compact'}</span>
                  </button>
                )}
                <button
                  onClick={newChat}
                  title="Start a new chat to clear active conversation context (Full Flush)"
                  className="flex items-center space-x-1 px-1.5 py-0.5 rounded bg-slate-800/80 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors text-[10px]"
                >
                  <Plus className="w-2.5 h-2.5" />
                  <span>New</span>
                </button>
              </div>
            </div>

            {showContextDetails && (
              <div className="mt-1.5 p-3 rounded-xl bg-slate-900/95 border border-slate-700/80 shadow-2xl space-y-2.5 text-xs animate-in fade-in zoom-in-95 duration-150">
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <div className="flex items-center space-x-2">
                    <Cpu className="w-4 h-4 text-cyan-400" />
                    <span className="font-semibold text-slate-100">Context Window Diagnostics</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-mono font-semibold ${
                      metrics.status === 'CRITICAL'
                        ? 'bg-rose-950 text-rose-300 border border-rose-700/60'
                        : metrics.status === 'HIGH'
                          ? 'bg-amber-950 text-amber-300 border border-amber-700/60'
                          : metrics.status === 'MODERATE'
                            ? 'bg-yellow-950 text-yellow-300 border border-yellow-700/60'
                            : 'bg-emerald-950 text-emerald-300 border border-emerald-700/60'
                    }`}>
                      {metrics.status} · {metrics.usage_percentage}%
                    </span>
                    <button
                      onClick={() => setShowContextDetails(false)}
                      className="p-1 hover:text-white text-slate-500 rounded hover:bg-slate-800"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Multi-segment visual token breakdown */}
                <div className="space-y-1">
                  <div className="flex justify-between text-[11px] text-slate-400 font-mono">
                    <span>{metrics.total_tokens.toLocaleString()} used</span>
                    <span>{metrics.max_tokens.toLocaleString()} capacity</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-800 overflow-hidden flex">
                    <div
                      style={{ width: `${Math.min(100, ((metrics.history_tokens || metrics.total_tokens) / metrics.max_tokens) * 100)}%` }}
                      className="h-full bg-cyan-500"
                      title={`Conversation History: ${(metrics.history_tokens || metrics.total_tokens).toLocaleString()} tokens`}
                    />
                    {metrics.system_tokens > 0 && (
                      <div
                        style={{ width: `${Math.min(100, (metrics.system_tokens / metrics.max_tokens) * 100)}%` }}
                        className="h-full bg-indigo-500"
                        title={`System Prompt & Rules: ${metrics.system_tokens.toLocaleString()} tokens`}
                      />
                    )}
                    {metrics.persistent_tokens > 0 && (
                      <div
                        style={{ width: `${Math.min(100, (metrics.persistent_tokens / metrics.max_tokens) * 100)}%` }}
                        className="h-full bg-emerald-500"
                        title={`Persistent Guidelines: ${metrics.persistent_tokens.toLocaleString()} tokens`}
                      />
                    )}
                  </div>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-[10px] text-slate-400">
                    <span className="flex items-center space-x-1">
                      <span className="w-2 h-2 rounded-full bg-cyan-500" />
                      <span>Turns: {(metrics.history_tokens || metrics.total_tokens).toLocaleString()}</span>
                    </span>
                    {metrics.system_tokens > 0 && (
                      <span className="flex items-center space-x-1">
                        <span className="w-2 h-2 rounded-full bg-indigo-500" />
                        <span>System: {metrics.system_tokens.toLocaleString()}</span>
                      </span>
                    )}
                    {metrics.persistent_tokens > 0 && (
                      <span className="flex items-center space-x-1">
                        <span className="w-2 h-2 rounded-full bg-emerald-500" />
                        <span>Memory: {metrics.persistent_tokens.toLocaleString()}</span>
                      </span>
                    )}
                    <span className="flex items-center space-x-1 text-slate-500">
                      <span>Free: {metrics.available_tokens.toLocaleString()}</span>
                    </span>
                  </div>
                </div>

                {/* Flushing & Compaction Actions */}
                <div className="pt-2 border-t border-slate-800/80 grid grid-cols-2 gap-2">
                  <button
                    onClick={handleCompact}
                    disabled={messages.length < 4 || compacting || busy}
                    className="p-2 rounded-lg bg-slate-800/90 hover:bg-slate-700/90 border border-slate-700 text-left transition-colors disabled:opacity-40"
                  >
                    <div className="flex items-center space-x-1.5 text-cyan-300 font-medium text-[11px]">
                      <Sparkles className="w-3.5 h-3.5" />
                      <span>Partial Flush (Compact)</span>
                    </div>
                    <p className="text-[10px] text-slate-400 mt-0.5 leading-snug">
                      Summarizes older messages into 1 turn, freeing ~70% of tokens while retaining context.
                    </p>
                  </button>

                  <button
                    onClick={async () => {
                      if (window.confirm('Clear all messages in this chat and reset context?')) {
                        await handleClearActiveChat();
                        setShowContextDetails(false);
                      }
                    }}
                    disabled={busy}
                    className="p-2 rounded-lg bg-slate-800/90 hover:bg-rose-950/60 border border-slate-700 hover:border-rose-800/60 text-left transition-colors disabled:opacity-40"
                  >
                    <div className="flex items-center space-x-1.5 text-rose-300 font-medium text-[11px]">
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Clear Chat Context</span>
                    </div>
                    <p className="text-[10px] text-slate-400 mt-0.5 leading-snug">
                      Flushes all messages in this conversation back to 0 tokens without deleting the chat.
                    </p>
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {/* Main Content Area: Side-by-side Fixed Sidebar when wide (>= 480px CSS) and open */}
        <div className="flex-1 flex overflow-hidden min-h-0 relative mt-2">
          {sidebarOpen && currentWidth >= 480 && (
            <FixedSidebar
              chats={chats}
              activeId={activeId}
              busy={busy}
              activeTab={sidebarTab}
              onTabChange={setSidebarTab}
              onOpenChat={openChat}
              onDeleteChat={deleteChat}
              onNewChat={newChat}
              skills={skills}
              loadingSkills={loadingSkills}
              projects={projects}
              loadingProjects={loadingProjects}
              activeProjectId={activeProjectId}
              onSelectProject={setActiveProjectId}
              onRefreshProjects={refreshProjects}
              artifacts={artifacts}
              loadingArtifacts={loadingArtifacts}
              onPreviewArtifact={setPreviewArtifact}
              onRefreshArtifacts={refreshArtifacts}
              connections={connections}
              connecting={connecting}
              connectNote={connectNote}
              onRefreshSkills={refreshSkills}
              onRefreshChats={refreshChats}
              onToggleConnection={toggleConnection}
              onActionClick={handleQuickAction}
              onClose={() => setSidebarOpen(false)}
              isOverlay={false}
              windows={windows}
              loadingWindows={loadingWindows}
              pinnedWindow={pinnedWindow}
              onPin={handlePin}
              onUnpin={handleUnpin}
              onInspectElements={handleToggleElements}
              onRefreshWindows={refreshWindows}
              browserStatus={browserStatus}
              loadingBrowser={loadingBrowser}
              onRefreshBrowserStatus={refreshBrowserStatus}
              onDeleteAllChats={deleteAllChats}
            />
          )}

          <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden pl-1">
            {messages.length === 0 ? (
              /* Claude-style centered Welcome & Hero Canvas */
              <div className="flex-1 flex flex-col items-center justify-center px-4 max-w-xl mx-auto w-full select-none">
                <div className="mb-4 flex items-center space-x-2">
                  <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-slate-900/90 border border-slate-800 text-[11px] text-slate-400 shadow-xs">
                    <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
                    <span>Local Engine · Connected</span>
                  </div>

                  {browserStatus.connected ? (
                    <div
                      title={`Chrome Companion Extension is connected (v${browserStatus.extension_info?.version || '1.0.0'}).`}
                      className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full bg-emerald-950/70 border border-emerald-700/60 text-[11px] text-emerald-300 shadow-xs"
                    >
                      <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
                      <Globe className="w-3 h-3 text-emerald-400" />
                      <span>Chrome Ext Active</span>
                    </div>
                  ) : (
                    <button
                      onClick={handleOpenBrowserSetup}
                      title="Chrome Companion Extension is disconnected. Click to open setup."
                      className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full bg-rose-950/80 border border-rose-600/70 text-[11px] text-rose-300 hover:bg-rose-900/80 transition-all shadow-xs cursor-pointer animate-pulse"
                    >
                      <span className="w-2 h-2 rounded-full bg-rose-500 shadow-[0_0_6px_#f43f5e]" />
                      <Globe className="w-3 h-3 text-rose-400" />
                      <span>Chrome Disconnected</span>
                      <AlertTriangle className="w-3 h-3 text-rose-400" />
                    </button>
                  )}
                </div>

                <h1 className="font-serif text-3xl md:text-4xl text-slate-100 font-normal tracking-tight text-center mb-6">
                  One year with Emiliano
                </h1>

                {/* Central Floating Composer Card */}
                <div className="w-full">
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
                    onToggleWindows={() => {
                      setShowWindows((open) => {
                        if (!open) refreshWindows();
                        return !open;
                      });
                    }}
                    busy={busy}
                    connected={!!ws}
                    onSend={send}
                    onStop={stop}
                    centered={true}
                  />
                </div>
              </div>
            ) : (
              /* Active Chat Conversation */
              <>
                <div className="flex-1 overflow-y-auto space-y-3 pr-1">
                  {messages.map((m) => (
                    <MessageBubble key={m.id} message={m} />
                  ))}
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
                    onUnloadAll={unloadAllLoaded}
                    connections={connections}
                    connecting={connecting}
                    connectNote={connectNote}
                    onToggleConnection={toggleConnection}
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
                  onToggleWindows={() => {
                    setShowWindows((open) => {
                      if (!open) refreshWindows();
                      return !open;
                    });
                  }}
                  busy={busy}
                  connected={!!ws}
                  onSend={send}
                  onStop={stop}
                />
              </>
            )}
          </div>
        </div>

        {previewArtifact && (
          <ArtifactPreviewModal
            artifact={previewArtifact}
            onClose={() => setPreviewArtifact(null)}
          />
        )}
      </div>
    </div>
  );
}

function EmilianoLogo({ connected = true, size = 28 }: { connected?: boolean; size?: number }) {
  return (
    <div className="relative shrink-0 flex items-center justify-center cursor-move" data-tauri-drag-region>
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="drop-shadow-[0_2px_8px_rgba(6,182,212,0.4)]"
      >
        <defs>
          <linearGradient id="emilianoGrad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#06b6d4" />
            <stop offset="50%" stopColor="#3b82f6" />
            <stop offset="100%" stopColor="#8b5cf6" />
          </linearGradient>
          <linearGradient id="innerGlow" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Base rounded squircle with gradient rim */}
        <rect x="2" y="2" width="28" height="28" rx="8" fill="#090d16" stroke="url(#emilianoGrad)" strokeWidth="1.5" />
        <rect x="2.5" y="2.5" width="27" height="27" rx="7.5" fill="url(#innerGlow)" opacity="0.1" />

        {/* Stylized Modern 'E' Cowork monogram */}
        <path
          d="M9 9.5H23C23.55 9.5 24 9.95 24 10.5C24 11.05 23.55 11.5 23 11.5H11.5V14H20C20.55 14 21 14.45 21 15C21 15.55 20.55 16 20 16H11.5V20.5H23C23.55 20.5 24 20.95 24 21.5C24 22.05 23.55 22.5 23 22.5H9C8.45 22.5 8 22.05 8 21.5V10.5C8 9.95 8.45 9.5 9 9.5Z"
          fill="url(#emilianoGrad)"
        />

        {/* Neural cowork AI sparkle diamond */}
        <path d="M21 6.5L22 9L24.5 10L22 11L21 13.5L20 11L17.5 10L20 9L21 6.5Z" fill="#38bdf8" />
      </svg>

      {/* Embedded connection status badge */}
      <span
        className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-slate-950 ${
          connected ? 'bg-emerald-400 shadow-[0_0_6px_#34d399]' : 'bg-amber-400 animate-pulse'
        }`}
        title={connected ? "Engine Connected" : "Starting Engine..."}
      />
    </div>
  );
}

function Header(props: {
  connected: boolean;
  browserStatus: { connected: boolean; extension_info: any };
  historyOpen: boolean;
  windowsOpen: boolean;
  sidebarOpen: boolean;
  currentWidth: number;
  pinnedTitle?: string;
  busy: boolean;
  onToggleSidebar: () => void;
  onToggleHistory: () => void;
  onToggleWindows: () => void;
  onCycleSize: () => void;
  onNewChat: () => void;
  onOpenBrowserSetup: () => void;
}) {
  const iconButton =
    'text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg p-1.5 transition-colors disabled:opacity-40';
  return (
    // data-tauri-drag-region: the window is frameless, so the header moves it
    <div
      data-tauri-drag-region
      className="flex items-center justify-between pb-3 border-b border-slate-800/80 cursor-move"
    >
      {/* Left controls: Claude-style sidebar toggle, split layout & history */}
      <div data-tauri-drag-region className="flex items-center space-x-1.5">
        <button
          title="Toggle Left Sidebar"
          onClick={props.onToggleSidebar}
          className={`${iconButton} ${props.sidebarOpen ? 'text-cyan-300 bg-slate-800/80' : ''}`}
        >
          <PanelLeft className="w-4 h-4" />
        </button>

        <button
          title="Toggle Split / HUD Columns"
          onClick={props.onCycleSize}
          className={`${iconButton}`}
        >
          <Columns className="w-4 h-4" />
        </button>

        <div className="flex items-center space-x-0.5 text-slate-500">
          <button
            title="Conversations & History"
            onClick={props.onToggleHistory}
            className="p-1 hover:text-slate-300 rounded hover:bg-slate-800/50"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
          </button>
          <button
            title="Forward"
            className="p-1 text-slate-600 cursor-not-allowed rounded"
            disabled
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Brand Logo & Name */}
        <div data-tauri-drag-region className="flex items-center space-x-2 pl-2">
          <EmilianoLogo connected={props.connected} size={24} />
          <div data-tauri-drag-region className="flex items-center space-x-1.5">
            <span
              data-tauri-drag-region
              className="text-xs font-bold tracking-wider text-slate-100"
            >
              EMILIANO
            </span>
            <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 font-semibold tracking-wide">
              COWORK
            </span>
          </div>
        </div>
      </div>

      {/* Right controls */}
      <div className="flex items-center space-x-1.5">
        {/* Chrome Extension Live Connection Indicator: Unmistakably clear when disconnected */}
        {props.browserStatus?.connected ? (
          <button
            onClick={props.onOpenBrowserSetup}
            title={`Chrome Companion Connected${
              props.browserStatus.extension_info?.version ? ` (v${props.browserStatus.extension_info.version})` : ''
            }. Background DOM automation active. Click to view companion.`}
            className="flex items-center space-x-1 px-1.5 py-0.5 rounded-full bg-emerald-950/70 border border-emerald-600/50 text-[10px] text-emerald-300 font-mono hover:bg-emerald-900/60 transition-colors cursor-pointer"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_5px_#34d399]" />
            <Globe className="w-3 h-3 text-emerald-400 shrink-0" />
            <span className="font-medium">{props.currentWidth >= 620 ? 'Chrome Ext' : 'Ext'}</span>
          </button>
        ) : (
          <button
            onClick={props.onOpenBrowserSetup}
            title="Chrome Companion Extension is DISCONNECTED! Click to open companion setup."
            className="flex items-center space-x-1 px-1.5 py-0.5 rounded-full bg-rose-950/90 border border-rose-500/80 text-[10px] text-rose-300 font-mono font-bold animate-pulse hover:bg-rose-900 transition-all cursor-pointer shadow-[0_0_8px_rgba(244,63,94,0.35)]"
          >
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500 shadow-[0_0_6px_#f43f5e]" />
            <Globe className="w-3 h-3 text-rose-400 shrink-0" />
            <span>{props.currentWidth >= 500 ? 'Chrome Offline' : 'Offline'}</span>
            <AlertTriangle className="w-2.5 h-2.5 text-rose-400 shrink-0" />
          </button>
        )}
        {/* HUD Width Preset Badge */}
        <button
          title={`HUD Width: ${props.currentWidth}px. Click to cycle (420px | 640px | 940px)`}
          onClick={props.onCycleSize}
          className={`${iconButton} text-[10px] font-mono flex items-center space-x-1 px-1.5 py-1`}
        >
          {props.currentWidth >= 550 ? (
            <Minimize2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
          ) : (
            <Maximize2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
          )}
          <span className="text-[10px] text-slate-300">
            {props.currentWidth < 350 ? '420' : props.currentWidth < 550 ? '640' : '940'}
          </span>
        </button>

        {/* Window Pinning */}
        <button
          title={
            props.pinnedTitle
              ? `Pinned to: ${props.pinnedTitle}`
              : 'Pin to target desktop window (e.g. Chrome, Excel)'
          }
          onClick={props.onToggleWindows}
          className={`${iconButton} ${
            props.pinnedTitle
              ? 'text-cyan-400 bg-cyan-950/80 border border-cyan-700/60'
              : props.windowsOpen
                ? 'bg-slate-700 text-white'
                : ''
          }`}
        >
          {props.pinnedTitle ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
        </button>

        {/* New Chat */}
        <button
          title="New chat"
          onClick={props.onNewChat}
          disabled={props.busy}
          className={iconButton}
        >
          <Plus className="w-4 h-4" />
        </button>

        {isTauri() && (
          <button
            title="Quit Emiliano"
            onClick={() => getCurrentWindow().close()}
            className={iconButton}
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}

function FixedSidebar(props: {
  chats: ChatSummary[];
  activeId: string | null;
  busy: boolean;
  activeTab: 'chats' | 'projects' | 'artifacts' | 'skills' | 'connects';
  onTabChange: (tab: 'chats' | 'projects' | 'artifacts' | 'skills' | 'connects') => void;
  onOpenChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onNewChat: () => void;
  skills: SkillItem[];
  loadingSkills: boolean;
  projects: ProjectItem[];
  loadingProjects: boolean;
  activeProjectId: string | null;
  onSelectProject: (id: string) => void;
  onRefreshProjects: () => void;
  artifacts: ArtifactItem[];
  loadingArtifacts: boolean;
  onPreviewArtifact: (artifact: ArtifactItem) => void;
  onRefreshArtifacts: () => void;
  connections: ServiceConnection[];
  connecting: string | null;
  connectNote: string | null;
  onRefreshSkills: () => void;
  onRefreshChats: () => void;
  onToggleConnection: (c: ServiceConnection) => void;
  onActionClick: (prompt: string) => void;
  onClose: () => void;
  isOverlay?: boolean;
  windows?: DesktopWindow[];
  loadingWindows?: boolean;
  pinnedWindow?: { hwnd: number; title: string } | null;
  onPin?: (w: DesktopWindow) => void;
  onUnpin?: () => void;
  onInspectElements?: () => void;
  onRefreshWindows?: () => void;
  browserStatus: { connected: boolean; extension_info: any };
  loadingBrowser: boolean;
  onRefreshBrowserStatus: () => void;
  onDeleteAllChats?: () => void;
}) {
  const [sidebarMode, setSidebarMode] = useState<'home' | 'cowork'>('home');
  const [coworkSubTab, setCoworkSubTab] = useState<'surface' | 'skills' | 'mcp' | 'data'>('surface');
  const [searchTerm, setSearchTerm] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [viewingSkill, setViewingSkill] = useState<{ id: string; title: string; content: string } | null>(null);
  const [approvingSkillId, setApprovingSkillId] = useState<string | null>(null);

  const handleApproveSkill = async (id: string) => {
    setApprovingSkillId(id);
    try {
      await coworkApi.approveSkill(id);
      props.onRefreshSkills();
    } catch (e) {
      console.error('Failed to approve skill:', e);
    } finally {
      setApprovingSkillId(null);
    }
  };

  const handleDiscardSkill = async (id: string) => {
    try {
      await coworkApi.discardSkill(id);
      props.onRefreshSkills();
    } catch (e) {
      console.error('Failed to discard skill:', e);
    }
  };

  const handleViewSkill = async (skill: SkillItem) => {
    try {
      const data = await coworkApi.getSkillContent(skill.id);
      setViewingSkill({
        id: skill.id,
        title: skill.title,
        content: data.instructions_md || skill.description || 'No instructions provided.',
      });
    } catch {
      setViewingSkill({
        id: skill.id,
        title: skill.title,
        content: skill.description || 'No instructions provided.',
      });
    }
  };

  useEffect(() => {
    if (props.activeTab === 'skills' || props.activeTab === 'connects') {
      setSidebarMode('cowork');
      setCoworkSubTab('surface');
    } else if (props.activeTab === 'chats' || props.activeTab === 'projects' || props.activeTab === 'artifacts') {
      setSidebarMode('home');
    }
  }, [props.activeTab]);

  useEffect(() => {
    if (sidebarMode === 'cowork') {
      props.onRefreshBrowserStatus();
      props.onRefreshWindows?.();
    }
  }, [sidebarMode, props.onRefreshBrowserStatus]);

  const filteredChats = useMemo(() => {
    if (!searchTerm.trim()) return props.chats;
    const q = searchTerm.toLowerCase();
    return props.chats.filter((c) => (c.title || '').toLowerCase().includes(q));
  }, [props.chats, searchTerm]);

  return (
    <div
      className={
        props.isOverlay
          ? "absolute inset-x-3 top-14 bottom-3 z-20 bg-slate-950/95 backdrop-blur-md border border-slate-700/80 rounded-2xl flex flex-col overflow-hidden shadow-2xl p-2.5"
          : "w-72 shrink-0 h-full border-r border-slate-800/80 pr-3 flex flex-col overflow-hidden select-none"
      }
    >
      {/* 1. Top Segmented Switcher: [ Home | <> Cowork ] exactly like Claude Desktop */}
      <div className="flex bg-slate-900/90 p-1 rounded-xl border border-slate-800/80 mb-2.5 shrink-0">
        <button
          onClick={() => {
            setSidebarMode('home');
            props.onTabChange('chats');
          }}
          className={`flex-1 py-1.5 px-3 rounded-lg text-xs font-medium flex items-center justify-center space-x-1.5 transition-all ${
            sidebarMode === 'home'
              ? 'bg-slate-800 text-white shadow-xs'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Compass className="w-3.5 h-3.5 text-cyan-400" />
          <span>Home</span>
        </button>
        <button
          onClick={() => {
            setSidebarMode('cowork');
            props.onTabChange('skills');
          }}
          className={`flex-1 py-1.5 px-3 rounded-lg text-xs font-medium flex items-center justify-center space-x-1.5 transition-all ${
            sidebarMode === 'cowork'
              ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 shadow-xs'
              : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Code2 className="w-3.5 h-3.5 text-cyan-400" />
          <span>Cowork</span>
        </button>
      </div>

      {sidebarMode === 'home' ? (
        props.activeTab === 'projects' ? (
          <ProjectsSubPanel
            projects={props.projects}
            loading={props.loadingProjects}
            activeProjectId={props.activeProjectId}
            onSelectProject={(id) => {
              props.onSelectProject(id);
              props.onTabChange('chats');
            }}
            onRefresh={props.onRefreshProjects}
            onBack={() => props.onTabChange('chats')}
          />
        ) : props.activeTab === 'artifacts' ? (
          <ArtifactsSubPanel
            artifacts={props.artifacts}
            projects={props.projects}
            loading={props.loadingArtifacts}
            onPreview={props.onPreviewArtifact}
            onRefresh={props.onRefreshArtifacts}
            onBack={() => props.onTabChange('chats')}
          />
        ) : (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            {/* 2. Action Items: + New, Search, Projects, Artifacts, Customize */}
            <div className="space-y-1 mb-2 shrink-0">
              {/* + New Button */}
              <button
                onClick={() => {
                  props.onNewChat();
                  if (props.isOverlay) props.onClose();
                }}
                disabled={props.busy}
                className="w-full py-1.5 px-3 rounded-xl bg-slate-800/90 hover:bg-slate-800 text-slate-100 border border-slate-700/60 flex items-center space-x-2 text-xs font-medium transition-all shadow-xs disabled:opacity-40"
              >
                <Plus className="w-4 h-4 text-slate-300" />
                <span>New</span>
              </button>

              {/* Search Button / Input */}
              {isSearching ? (
                <div className="relative flex items-center">
                  <Search className="w-3.5 h-3.5 absolute left-3 text-slate-400 pointer-events-none" />
                  <input
                    type="text"
                    autoFocus
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="Search conversations…"
                    className="w-full bg-slate-900 border border-cyan-500/60 rounded-xl pl-9 pr-7 py-1.5 text-xs text-slate-200 placeholder-slate-400 focus:outline-none"
                  />
                  <button
                    onClick={() => {
                      setSearchTerm('');
                      setIsSearching(false);
                    }}
                    className="absolute right-2.5 text-slate-400 hover:text-white"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setIsSearching(true)}
                  className="w-full px-3 py-1.5 rounded-xl hover:bg-slate-800/50 text-slate-300 hover:text-white flex items-center space-x-2.5 text-xs transition-colors"
                >
                  <Search className="w-4 h-4 text-slate-400" />
                  <span>Search</span>
                </button>
              )}

              {/* Projects */}
              <button
                onClick={() => {
                  setSidebarMode('home');
                  props.onTabChange('projects');
                }}
                className="w-full px-3 py-1.5 rounded-xl text-xs transition-colors flex items-center justify-between hover:bg-slate-800/50 text-slate-300 hover:text-white"
              >
                <div className="flex items-center space-x-2.5">
                  <FolderGit2 className="w-4 h-4 text-slate-400" />
                  <span>Projects</span>
                </div>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-400">
                  {props.projects.length}
                </span>
              </button>

              {/* Artifacts */}
              <button
                onClick={() => {
                  setSidebarMode('home');
                  props.onTabChange('artifacts');
                }}
                className="w-full px-3 py-1.5 rounded-xl text-xs transition-colors flex items-center justify-between hover:bg-slate-800/50 text-slate-300 hover:text-white"
              >
                <div className="flex items-center space-x-2.5">
                  <FileText className="w-4 h-4 text-slate-400" />
                  <span>Artifacts</span>
                </div>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-400">
                  {props.artifacts.length}
                </span>
              </button>

              {/* Customize */}
              <button
                onClick={() => {
                  setSidebarMode('cowork');
                  props.onTabChange('connects');
                }}
                className="w-full px-3 py-1.5 rounded-xl text-xs transition-colors flex items-center justify-between hover:bg-slate-800/50 text-slate-300 hover:text-white"
              >
                <div className="flex items-center space-x-2.5">
                  <SlidersHorizontal className="w-4 h-4 text-slate-400" />
                  <span>Customize</span>
                </div>
                <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_6px_#34d399]" />
              </button>
            </div>

          {/* 3. Section Header: Chats and tasks ⌄ */}
          <div className="pt-2 pb-1.5 px-1 flex items-center justify-between text-[11px] font-semibold text-slate-400 shrink-0">
            <div className="flex items-center space-x-1 cursor-pointer hover:text-slate-200">
              <span>Chats and tasks</span>
              <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
            </div>
            <div className="flex items-center space-x-1">
              {filteredChats.length > 0 && props.onDeleteAllChats && (
                <button
                  onClick={() => {
                    const fn = props.onDeleteAllChats;
                    if (fn && window.confirm('Flush total history? This will delete all saved conversations.')) {
                      fn();
                    }
                  }}
                  title="Flush total conversations (Delete all chats)"
                  className="p-1 hover:text-rose-400 text-slate-500 transition-colors"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              )}
              <button
                onClick={() => {
                  props.onRefreshChats();
                  props.onRefreshSkills();
                }}
                title="Refresh conversations"
                className="p-1 hover:text-white text-slate-500 transition-colors"
              >
                <RefreshCw className="w-3 h-3" />
              </button>
            </div>
          </div>

          {/* 4. Conversation List Items with Claude-style status dots */}
          <div className="flex-1 overflow-y-auto space-y-0.5 pr-1">
            {filteredChats.length === 0 ? (
              <div className="p-4 text-xs text-slate-500 text-center">
                {searchTerm ? `No chats matching "${searchTerm}"` : 'No saved chats yet.'}
              </div>
            ) : (
              filteredChats.map((chat) => {
                const isActive = chat.id === props.activeId;
                const isConfirming = confirmingDelete === chat.id;
                const isWarning =
                  chat.title?.toLowerCase().includes('error') ||
                  chat.title?.toLowerCase().includes('job') ||
                  chat.title?.toLowerCase().includes('alert');

                return (
                  <div
                    key={chat.id}
                    onClick={() => {
                      if (!isConfirming) {
                        props.onOpenChat(chat.id);
                        if (props.isOverlay) props.onClose();
                      }
                    }}
                    className={`group flex items-center px-2.5 py-1.5 text-xs rounded-xl cursor-pointer transition-colors ${
                      isActive
                        ? 'bg-slate-800 text-white font-medium shadow-xs'
                        : 'hover:bg-slate-800/40 text-slate-300 hover:text-slate-100'
                    }`}
                  >
                    {isConfirming ? (
                      <div
                        className="flex items-center justify-between w-full py-0.5"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <span className="text-[11px] text-rose-300 truncate">Delete?</span>
                        <div className="flex items-center space-x-1 shrink-0">
                          <button
                            onClick={() => {
                              props.onDeleteChat(chat.id);
                              setConfirmingDelete(null);
                            }}
                            className="px-1.5 py-0.5 rounded bg-rose-600 hover:bg-rose-500 text-white text-[10px]"
                          >
                            Yes
                          </button>
                          <button
                            onClick={() => setConfirmingDelete(null)}
                            className="px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 text-[10px]"
                          >
                            No
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        {/* Claude-style indicator dot */}
                        {isWarning ? (
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-400 mr-2.5 shrink-0" />
                        ) : isActive ? (
                          <span className="w-2 h-2 rounded-full bg-cyan-400 mr-2.5 shrink-0 shadow-[0_0_6px_#38bdf8]" />
                        ) : (
                          <span className="w-2 h-2 rounded-full border border-slate-500 mr-2.5 shrink-0 group-hover:border-slate-300" />
                        )}

                        <div className="min-w-0 flex-1 truncate">{chat.title || 'Untitled chat'}</div>

                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmingDelete(chat.id);
                          }}
                          title="Delete chat"
                          className="opacity-0 group-hover:opacity-100 p-1 hover:text-rose-400 text-slate-500 transition-opacity ml-1 shrink-0"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
        )
      ) : (
        /* Cowork Panels (Surface, Skills, MCP, Data) */
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* 4-Way Segmented Cowork Tab Bar */}
          <div className="grid grid-cols-4 gap-1 bg-slate-900/90 border border-slate-800/80 rounded-xl p-1 mb-2.5 shrink-0 text-[11px]">
            <button
              onClick={() => setCoworkSubTab('surface')}
              className={`py-1.5 px-0.5 text-center font-medium rounded-lg transition-all flex flex-col items-center justify-center space-y-0.5 ${
                coworkSubTab === 'surface'
                  ? 'bg-slate-800 text-cyan-300 shadow-xs border border-cyan-800/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Execution Surface (Browser & Window Canvas)"
            >
              <Monitor className="w-3.5 h-3.5" />
              <span className="text-[10px]">Surface</span>
            </button>
            <button
              onClick={() => setCoworkSubTab('skills')}
              className={`py-1.5 px-0.5 text-center font-medium rounded-lg transition-all flex flex-col items-center justify-center space-y-0.5 ${
                coworkSubTab === 'skills'
                  ? 'bg-slate-800 text-cyan-300 shadow-xs border border-cyan-800/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Domain Skills & Playbooks"
            >
              <Zap className="w-3.5 h-3.5" />
              <span className="text-[10px]">Skills ({props.skills.length})</span>
            </button>
            <button
              onClick={() => setCoworkSubTab('mcp')}
              className={`py-1.5 px-0.5 text-center font-medium rounded-lg transition-all flex flex-col items-center justify-center space-y-0.5 ${
                coworkSubTab === 'mcp'
                  ? 'bg-slate-800 text-cyan-300 shadow-xs border border-cyan-800/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Model Context Protocol Servers"
            >
              <Blocks className="w-3.5 h-3.5" />
              <span className="text-[10px]">MCP ({props.connections.length})</span>
            </button>
            <button
              onClick={() => setCoworkSubTab('data')}
              className={`py-1.5 px-0.5 text-center font-medium rounded-lg transition-all flex flex-col items-center justify-center space-y-0.5 ${
                coworkSubTab === 'data'
                  ? 'bg-slate-800 text-cyan-300 shadow-xs border border-cyan-800/40'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Attached Datastores & CRM Context"
            >
              <Database className="w-3.5 h-3.5" />
              <span className="text-[10px]">Data</span>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {/* SUBTAB 1: SURFACE (Execution Canvas) */}
            {coworkSubTab === 'surface' && (
              <>
                {/* Background Browser Companion Card */}
                <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-100">
                      <Globe className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                      <span>Chrome Companion</span>
                    </div>
                    <span
                      className={`text-[9px] px-1.5 py-0.5 rounded font-medium border flex items-center space-x-1 ${
                        props.browserStatus.connected
                          ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800/40'
                          : 'bg-rose-950/80 text-rose-400 border-rose-800/40'
                      }`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${props.browserStatus.connected ? 'bg-emerald-400' : 'bg-rose-500 animate-pulse'}`} />
                      <span>{props.browserStatus.connected ? 'Active (Background)' : 'Offline'}</span>
                    </span>
                  </div>

                  <p className="text-[11px] text-slate-400 leading-relaxed">
                    {props.browserStatus.connected
                      ? `Silent DOM injection, background tab navigation, and visual receipts with zero mouse movement (v${props.browserStatus.extension_info?.version || '1.0.0'}).`
                      : 'Load the Emiliano Companion Extension in Google Chrome (chrome://extensions) to enable background browser automation.'}
                  </p>

                  <div className="pt-1 border-t border-slate-800/60 flex items-center justify-between text-[10px]">
                    <span className="text-slate-500 font-mono">
                      {props.browserStatus.connected ? 'Tier 1: Chrome Extension' : 'Status: Disconnected'}
                    </span>
                    <button
                      onClick={props.onRefreshBrowserStatus}
                      disabled={props.loadingBrowser}
                      className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 flex items-center space-x-1 text-[10px] transition-colors"
                    >
                      <RefreshCw className={`w-2.5 h-2.5 ${props.loadingBrowser ? 'animate-spin' : ''}`} />
                      <span>{props.loadingBrowser ? 'Checking…' : 'Ping'}</span>
                    </button>
                  </div>
                </div>

                {/* OS Desktop Window Surface Card */}
                <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-100">
                      <Monitor className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                      <span>OS Window Binding</span>
                    </div>
                    {props.pinnedWindow ? (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-800/40 font-mono">
                        HWND {props.pinnedWindow.hwnd}
                      </span>
                    ) : (
                      <span className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 font-mono">
                        Unbound
                      </span>
                    )}
                  </div>

                  {props.pinnedWindow ? (
                    <div className="space-y-2">
                      <div className="text-[11px] text-slate-300 bg-slate-950/60 p-2 rounded-lg border border-slate-800/80 flex items-center justify-between">
                        <span className="truncate pr-2 font-medium">{props.pinnedWindow.title}</span>
                        <button
                          onClick={props.onUnpin}
                          title="Unpin window"
                          className="text-slate-500 hover:text-rose-400 transition-colors shrink-0 p-1"
                        >
                          <PinOff className="w-3 h-3" />
                        </button>
                      </div>

                      <div className="flex items-center space-x-1.5">
                        <button
                          onClick={props.onInspectElements}
                          className="flex-1 py-1 px-2 rounded-lg bg-cyan-950/80 hover:bg-cyan-900/80 text-cyan-300 border border-cyan-800/50 text-[10px] font-medium transition-colors flex items-center justify-center space-x-1 shadow-xs"
                        >
                          <Crosshair className="w-3 h-3 text-cyan-400" />
                          <span>Inspect UI Tree</span>
                        </button>
                        <button
                          onClick={props.onUnpin}
                          className="py-1 px-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] transition-colors"
                        >
                          Unpin
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-1.5">
                      <p className="text-[11px] text-slate-400">
                        Pin an active application window to restrict synthetic keyboard & mouse cowork actions.
                      </p>
                      {props.windows && props.windows.length > 0 && (
                        <div className="max-h-28 overflow-y-auto space-y-1 pt-1">
                          {props.windows.slice(0, 5).map((w) => (
                            <div
                              key={w.hwnd}
                              className="px-2 py-1 rounded bg-slate-950/50 hover:bg-slate-800/60 border border-slate-800/60 flex items-center justify-between text-[10px] transition-colors"
                            >
                              <span className="truncate pr-2 text-slate-300">{w.title}</span>
                              <button
                                onClick={() => props.onPin?.(w)}
                                className="text-cyan-400 hover:text-cyan-300 shrink-0 font-medium px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/40"
                              >
                                Pin
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Safety Rails Telemetry */}
                <div className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-1.5 text-[10px]">
                  <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-300">
                    <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
                    <span>Safety Guardrails</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-400 pt-0.5">
                    <span>Emergency Stop:</span>
                    <span className="font-mono text-amber-400 font-semibold">[Esc] Key Armed</span>
                  </div>
                  <div className="flex items-center justify-between text-slate-400">
                    <span>Countdown Preview:</span>
                    <span className="font-mono text-cyan-400 font-medium">400ms Shadow Window</span>
                  </div>
                </div>
              </>
            )}

            {/* SUBTAB 2: SKILLS (Active + Auto-Synthesized Drafts) */}
            {coworkSubTab === 'skills' && (() => {
              const stagedSkills = props.skills.filter((s) => s.status === 'staged');
              const activeSkills = props.skills.filter((s) => s.status !== 'staged');

              return (
                <div className="space-y-3">
                  {/* Hermes Learning Loop: Staged Auto-Synthesized Skills */}
                  {stagedSkills.length > 0 && (
                    <div className="p-2.5 rounded-xl bg-amber-950/30 border border-amber-800/60 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-1.5 text-xs font-semibold text-amber-200">
                          <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                          <span>Auto-Synthesized Drafts ({stagedSkills.length})</span>
                        </div>
                        <span className="text-[9px] text-amber-400/80 uppercase font-semibold tracking-wider">Awaiting Approval</span>
                      </div>
                      <p className="text-[10px] text-amber-300/70">
                        Captured by Hermes review loop from recent task execution. Review and activate below:
                      </p>
                      {stagedSkills.map((skill) => (
                        <div key={skill.id} className="p-2 rounded-lg bg-slate-900/90 border border-amber-800/40 space-y-1.5">
                          <div className="flex items-start justify-between">
                            <span className="text-xs font-semibold text-slate-100">{skill.title}</span>
                            <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-700/60 font-mono">
                              staged
                            </span>
                          </div>
                          <p className="text-[11px] text-slate-400 line-clamp-2">{skill.description}</p>
                          <div className="flex items-center space-x-2 pt-1">
                            <button
                              onClick={() => handleApproveSkill(skill.id)}
                              disabled={approvingSkillId === skill.id}
                              className="px-2.5 py-1 rounded-md bg-emerald-700 hover:bg-emerald-600 text-white text-[10px] font-semibold flex items-center space-x-1 transition-colors shadow-xs"
                            >
                              <CheckCircle2 className="w-3 h-3" />
                              <span>{approvingSkillId === skill.id ? 'Activating…' : 'Approve & Activate'}</span>
                            </button>
                            <button
                              onClick={() => handleDiscardSkill(skill.id)}
                              className="px-2 py-1 rounded-md bg-red-950/80 hover:bg-red-900 text-red-300 border border-red-800/60 text-[10px] font-semibold flex items-center space-x-1 transition-colors"
                            >
                              <Trash2 className="w-3 h-3" />
                              <span>Discard</span>
                            </button>
                            <button
                              onClick={() => handleViewSkill(skill)}
                              className="px-2 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] flex items-center space-x-1"
                            >
                              <span>View Runbook</span>
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Active Registered Skills */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between px-0.5">
                      <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
                        Active Skills ({activeSkills.length})
                      </span>
                      <button
                        onClick={props.onRefreshSkills}
                        title="Rescan skill library"
                        className="text-slate-400 hover:text-cyan-400 transition-colors p-0.5"
                      >
                        <RefreshCw className="w-3 h-3" />
                      </button>
                    </div>

                    {activeSkills.length === 0 && (
                      <div className="text-center py-6 text-xs text-slate-500">
                        {props.loadingSkills ? 'Scanning workspace skills…' : 'No companion skills found.'}
                      </div>
                    )}

                    {activeSkills.map((skill) => (
                      <div
                        key={skill.id}
                        className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 hover:border-cyan-700/50 transition-all space-y-2 shadow-sm"
                      >
                        <div className="flex items-start justify-between">
                          <div className="min-w-0 pr-1">
                            <div className="flex items-center space-x-1.5">
                              <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                              <span className="text-xs font-semibold text-slate-100 truncate">{skill.title}</span>
                            </div>
                            {skill.badge && (
                              <span className="mt-1 inline-block text-[9px] px-1.5 py-0.2 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-800/60 font-medium">
                                {skill.badge}
                              </span>
                            )}
                          </div>
                          <span className="inline-flex items-center space-x-1 text-[10px] text-emerald-400 bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-800/40 shrink-0 font-medium">
                            <CheckCircle2 className="w-3 h-3" />
                            <span>Active</span>
                          </span>
                        </div>

                        <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">{skill.description}</p>

                        <div className="flex items-center justify-between pt-1 border-t border-slate-800/60">
                          <button
                            onClick={() => handleViewSkill(skill)}
                            className="text-[10px] text-cyan-400 hover:text-cyan-300 underline font-medium"
                          >
                            View Playbook & Instructions
                          </button>
                        </div>

                        {skill.quickActions && skill.quickActions.length > 0 && (
                          <div className="pt-1 border-t border-slate-800/40 space-y-1">
                            <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">Quick Actions</div>
                            <div className="flex flex-wrap gap-1">
                              {skill.quickActions.map((action, i) => (
                                <button
                                  key={i}
                                  onClick={() => props.onActionClick(action)}
                                  className="px-2 py-0.5 rounded-md bg-slate-800 hover:bg-cyan-950 hover:text-cyan-300 text-slate-300 text-[10px] border border-slate-700/60 hover:border-cyan-700/60 transition-colors flex items-center space-x-1 font-mono"
                                >
                                  <Play className="w-2.5 h-2.5 text-cyan-400 shrink-0" />
                                  <span className="truncate max-w-[150px]">{action}</span>
                                </button>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* Playbook Preview Modal */}
                  {viewingSkill && (
                    <div className="p-3 rounded-xl bg-slate-950 border border-cyan-800/80 shadow-xl space-y-2">
                      <div className="flex items-center justify-between border-b border-slate-800 pb-1.5">
                        <div className="flex items-center space-x-1.5 text-xs font-semibold text-cyan-300">
                          <Zap className="w-3.5 h-3.5 text-cyan-400" />
                          <span>{viewingSkill.title}</span>
                        </div>
                        <button
                          onClick={() => setViewingSkill(null)}
                          className="text-slate-400 hover:text-white text-xs px-1"
                        >
                          ✕
                        </button>
                      </div>
                      <div className="text-[11px] font-mono text-slate-300 max-h-48 overflow-y-auto whitespace-pre-wrap bg-slate-900/90 p-2 rounded-lg border border-slate-800">
                        {viewingSkill.content}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* SUBTAB 3: MCP PROTOCOLS */}
            {coworkSubTab === 'mcp' && (
              <>
                <div className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800 space-y-1">
                  <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-200">
                    <Blocks className="w-3.5 h-3.5 text-cyan-400" />
                    <span>Model Context Protocol</span>
                  </div>
                  <p className="text-[11px] text-slate-400">
                    Anthropic open standard client connections providing standardized tools and resources.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold px-1">
                    Connected Servers ({props.connections.length})
                  </div>
                  {props.connections.map((c) => (
                    <div
                      key={c.service}
                      className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 flex items-center justify-between shadow-xs"
                    >
                      <div className="min-w-0 pr-1">
                        <div className="text-xs text-slate-200 font-medium truncate">{c.title}</div>
                        <div className="text-[10px] font-mono flex items-center space-x-1 mt-0.5">
                          <span className={`w-1.5 h-1.5 rounded-full ${c.connected ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                          <span className={c.connected ? 'text-emerald-400' : 'text-slate-500'}>
                            {c.connected ? 'Connected' : 'Offline'}
                          </span>
                        </div>
                      </div>
                      <button
                        onClick={() => props.onToggleConnection(c)}
                        disabled={props.connecting === c.service}
                        className={`px-2.5 py-1 rounded-lg text-[10px] font-medium transition-colors ${
                          c.connected
                            ? 'bg-slate-800 hover:bg-rose-950 text-slate-400 hover:text-rose-300 border border-slate-700/60'
                            : 'bg-cyan-600 hover:bg-cyan-500 text-white'
                        }`}
                      >
                        {props.connecting === c.service ? '…' : c.connected ? 'Disconnect' : 'Connect'}
                      </button>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* SUBTAB 4: DATA & CRM */}
            {coworkSubTab === 'data' && (
              <>
                <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-200">
                      <Database className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Excel B2B CRM</span>
                    </div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/40 font-mono">
                      1,586 leads
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 font-mono text-[10px] truncate">
                    baza_klientow_warszawa_krakow.xlsx
                  </p>
                  <div className="pt-1 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-500">
                    <span>Delivered DMs:</span>
                    <span className="text-emerald-400 font-mono font-medium">216 verified</span>
                  </div>
                </div>

                <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-200">
                      <Database className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Audit Log (JSONL)</span>
                    </div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-800/40">
                      Real-time
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 font-mono text-[10px] truncate">
                    business_logs.jsonl
                  </p>
                  <p className="text-[10px] text-slate-500">
                    Cryptographic audit trail tracking all outreach dispatches & DOM proof receipts.
                  </p>
                </div>

                <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-200">
                      <Layers className="w-3.5 h-3.5 text-purple-400" />
                      <span>Blackboard Memory</span>
                    </div>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-950/80 text-purple-300 border border-purple-800/40">
                      Sync
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-400">
                    Cross-session entity state, active goals, and domain context cache.
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* 5. Bottom Profile Footer: Avatar [A] Artur · Emiliano Pro ⌄ */}
      <div className="pt-2 mt-auto border-t border-slate-800/80 px-1 py-1.5 flex items-center justify-between bg-slate-950/40 shrink-0">
        <div className="flex items-center space-x-2 cursor-pointer hover:opacity-90">
          <div className="w-6 h-6 rounded-full bg-amber-600 flex items-center justify-center text-xs font-bold text-white shadow-xs">
            A
          </div>
          <div className="flex items-center space-x-1 text-xs font-medium text-slate-200">
            <span>Artur · Emiliano Pro</span>
            <ChevronDown className="w-3 h-3 text-slate-400" />
          </div>
        </div>
        <button
          onClick={props.onClose}
          title="Collapse sidebar"
          className="p-1 text-slate-400 hover:text-white transition-colors"
        >
          <PanelLeftClose className="w-3.5 h-3.5" />
        </button>
      </div>

    </div>
  );
}

function ProjectsSubPanel(props: {
  projects: ProjectItem[];
  loading: boolean;
  activeProjectId: string | null;
  onSelectProject: (id: string) => void;
  onRefresh: () => void;
  onBack: () => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [rootPath, setRootPath] = useState('C:\\Users\\artlu\\OracliomNew\\Oracliom');
  const [desc, setDesc] = useState('');
  const [prompt, setPrompt] = useState('');
  const [creating, setCreating] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !rootPath.trim()) return;
    setCreating(true);
    try {
      await projectsApi.create({
        name: name.trim(),
        root_path: rootPath.trim(),
        description: desc.trim(),
        system_prompt: prompt.trim(),
      });
      setName('');
      setDesc('');
      setPrompt('');
      setShowCreate(false);
      props.onRefresh();
    } catch (err) {
      console.error('Failed to create project:', err);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800 shrink-0">
        <button
          onClick={props.onBack}
          className="flex items-center space-x-1 text-slate-400 hover:text-slate-100 text-xs transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          <span>Chats</span>
        </button>
        <span className="text-xs font-semibold text-slate-200">Local Projects</span>
        <button
          onClick={() => setShowCreate((v) => !v)}
          className="p-1 rounded bg-slate-800 hover:bg-cyan-900/60 text-cyan-300 transition-colors"
          title="Add local project workspace"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="p-2.5 rounded-xl bg-slate-900 border border-cyan-800/60 my-2 space-y-2 shrink-0">
          <div className="text-[11px] font-semibold text-cyan-300">Add Workspace Project</div>
          <input
            type="text"
            placeholder="Project name (e.g. My Next.js App)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none"
            required
          />
          <input
            type="text"
            placeholder="Root folder path (e.g. C:/code/project)"
            value={rootPath}
            onChange={(e) => setRootPath(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none font-mono text-[10px]"
            required
          />
          <input
            type="text"
            placeholder="Short description (optional)"
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none"
          />
          <div className="flex justify-end space-x-1.5 pt-1">
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="px-2 py-0.5 rounded text-xs text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating}
              className="px-2.5 py-0.5 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium disabled:opacity-50"
            >
              {creating ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      )}

      {props.activeProjectId && (
        <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-cyan-950/60 border border-cyan-800/60 mt-1 mb-1 text-xs shrink-0">
          <span className="text-cyan-300 text-[11px]">Filtered by active project</span>
          <button
            onClick={() => props.onSelectProject('')}
            className="text-[10px] text-cyan-400 hover:text-white underline"
          >
            Show All
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto space-y-2 pr-1 pt-1">
        {props.projects.length === 0 ? (
          <div className="text-center py-8 text-xs text-slate-500">
            {props.loading ? 'Loading projects…' : 'No local projects found.'}
          </div>
        ) : (
          props.projects.map((proj) => {
            const isActive = proj.id === props.activeProjectId;
            return (
              <div
                key={proj.id}
                onClick={() => {
                  props.onSelectProject(isActive ? '' : proj.id);
                }}
                className={`p-2.5 rounded-xl border transition-all cursor-pointer ${
                  isActive
                    ? 'bg-slate-800/90 border-cyan-500/80 shadow-xs'
                    : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-1.5 font-semibold text-xs text-slate-200">
                    <FolderGit2 className="w-3.5 h-3.5 text-cyan-400" />
                    <span className="truncate">{proj.name}</span>
                  </div>
                  {isActive && (
                    <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                      Active
                    </span>
                  )}
                </div>
                {proj.description && (
                  <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">{proj.description}</p>
                )}
                <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-slate-500 pt-1 border-t border-slate-800/40">
                  <span className="truncate max-w-[190px]" title={proj.root_path}>📁 {proj.root_path}</span>
                  <button
                    onClick={async (e) => {
                      e.stopPropagation();
                      try {
                        await projectsApi.openFolder(proj.id);
                      } catch (err) {
                        console.error('Failed to open folder:', err);
                      }
                    }}
                    title="Open project folder in Windows Explorer"
                    className="p-1 hover:text-cyan-300 text-slate-400 hover:bg-slate-700/50 rounded transition-colors"
                  >
                    <FolderGit2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function ArtifactsSubPanel(props: {
  artifacts: ArtifactItem[];
  projects: ProjectItem[];
  loading: boolean;
  onPreview: (artifact: ArtifactItem) => void;
  onRefresh: () => void;
  onBack: () => void;
}) {
  const [kindFilter, setKindFilter] = useState<'all' | 'html' | 'code' | 'diagram' | 'plan' | 'markdown'>('all');

  const filtered = useMemo(() => {
    if (kindFilter === 'all') return props.artifacts;
    return props.artifacts.filter((a) => a.kind === kindFilter);
  }, [props.artifacts, kindFilter]);

  const kindBadge = (k: string) => {
    switch (k) {
      case 'html':
        return <span className="text-[9px] px-1.5 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 font-mono font-medium">HTML</span>;
      case 'diagram':
        return <span className="text-[9px] px-1.5 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-800 font-mono">Diagram</span>;
      case 'plan':
        return <span className="text-[9px] px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-mono">Plan</span>;
      case 'code':
        return <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-950 text-amber-300 border border-amber-800 font-mono">Code</span>;
      default:
        return <span className="text-[9px] px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 font-mono">Doc</span>;
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800 shrink-0">
        <button
          onClick={props.onBack}
          className="flex items-center space-x-1 text-slate-400 hover:text-slate-100 text-xs transition-colors"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
          <span>Chats</span>
        </button>
        <span className="text-xs font-semibold text-slate-200">Workspace Artifacts</span>
        <button
          onClick={props.onRefresh}
          className="p-1 rounded text-slate-400 hover:text-white transition-colors"
          title="Refresh artifacts"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Filter chips */}
      <div className="flex space-x-1 py-2 shrink-0 overflow-x-auto text-[10px]">
        {(['all', 'html', 'diagram', 'plan', 'code', 'markdown'] as const).map((k) => (
          <button
            key={k}
            onClick={() => setKindFilter(k)}
            className={`px-2 py-0.5 rounded-full capitalize transition-colors ${
              kindFilter === k
                ? 'bg-slate-700 text-white font-medium shadow-xs'
                : 'bg-slate-900 text-slate-400 hover:text-slate-200'
            }`}
          >
            {k === 'all' ? 'All' : k}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto space-y-2 pr-1 pt-1">
        {filtered.length === 0 ? (
          <div className="text-center py-8 text-xs text-slate-500">
            {props.loading ? 'Loading artifacts…' : 'No artifacts found for this filter.'}
          </div>
        ) : (
          filtered.map((art) => {
            const proj = props.projects.find((p) => p.id === art.project_id);
            return (
              <div
                key={art.id}
                onClick={() => props.onPreview(art)}
                className="p-2.5 rounded-xl bg-slate-900/70 border border-slate-800 hover:border-cyan-600/60 transition-all cursor-pointer group"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 pr-1">
                    <span className="text-xs font-semibold text-slate-200 group-hover:text-cyan-300 transition-colors truncate block">
                      {art.title}
                    </span>
                    {proj && (
                      <span className="text-[9px] text-cyan-400/80 font-mono block truncate">
                        📁 {proj.name}
                      </span>
                    )}
                  </div>
                  {kindBadge(art.kind)}
                </div>
                <p className="text-[11px] text-slate-400 mt-1 line-clamp-2 font-mono text-[10px]">
                  {art.content.slice(0, 140)}
                </p>
                <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500">
                  <span>{relativeTime(art.created_at)}</span>
                  <span className="text-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity">View →</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function ArtifactPreviewModal(props: {
  artifact: ArtifactItem;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const isHtml =
    props.artifact.kind === 'html' ||
    props.artifact.content.trim().startsWith('<!DOCTYPE html>') ||
    /<html[\s>]/i.test(props.artifact.content);
  const [viewMode, setViewMode] = useState<'preview' | 'code'>('preview');
  const [viewport, setViewport] = useState<'desktop' | 'tablet' | 'mobile'>('desktop');

  const handleCopy = () => {
    navigator.clipboard.writeText(props.artifact.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="absolute inset-2 z-40 bg-slate-950/98 border border-slate-700 rounded-2xl flex flex-col overflow-hidden shadow-2xl backdrop-blur-xl">
      <div className="px-4 py-3 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-2.5 min-w-0">
          {isHtml ? (
            <Globe className="w-4 h-4 text-indigo-400 shrink-0" />
          ) : (
            <FileText className="w-4 h-4 text-cyan-400 shrink-0" />
          )}
          <div className="truncate">
            <div className="flex items-center space-x-2">
              <h3 className="text-sm font-bold text-white truncate">{props.artifact.title}</h3>
              {isHtml && (
                <span className="text-[9px] px-1.5 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 font-mono font-medium">
                  Interactive HTML
                </span>
              )}
            </div>
            {props.artifact.file_path && (
              <span className="text-[10px] font-mono text-slate-400 truncate block">
                {props.artifact.file_path}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          {isHtml && (
            <div className="flex items-center space-x-1 bg-slate-800/80 p-0.5 rounded-lg border border-slate-700/60 mr-2">
              <button
                onClick={() => setViewMode('preview')}
                className={`flex items-center space-x-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  viewMode === 'preview'
                    ? 'bg-indigo-600 text-white shadow-xs'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                title="Interactive HTML Preview"
              >
                <Eye className="w-3.5 h-3.5" />
                <span>Preview</span>
              </button>
              <button
                onClick={() => setViewMode('code')}
                className={`flex items-center space-x-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  viewMode === 'code'
                    ? 'bg-indigo-600 text-white shadow-xs'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                title="View HTML Source Code"
              >
                <Code className="w-3.5 h-3.5" />
                <span>Code</span>
              </button>
            </div>
          )}

          {isHtml && viewMode === 'preview' && (
            <div className="hidden sm:flex items-center space-x-1 bg-slate-800/80 p-0.5 rounded-lg border border-slate-700/60 mr-2">
              <button
                onClick={() => setViewport('desktop')}
                className={`p-1 rounded transition-colors ${
                  viewport === 'desktop' ? 'bg-slate-700 text-cyan-300' : 'text-slate-400 hover:text-slate-200'
                }`}
                title="Desktop View (100%)"
              >
                <Monitor className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setViewport('tablet')}
                className={`p-1 rounded transition-colors ${
                  viewport === 'tablet' ? 'bg-slate-700 text-cyan-300' : 'text-slate-400 hover:text-slate-200'
                }`}
                title="Tablet View (768px)"
              >
                <Tablet className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setViewport('mobile')}
                className={`p-1 rounded transition-colors ${
                  viewport === 'mobile' ? 'bg-slate-700 text-cyan-300' : 'text-slate-400 hover:text-slate-200'
                }`}
                title="Mobile View (375px)"
              >
                <Smartphone className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {props.artifact.file_path && (
            <button
              onClick={async () => {
                try {
                  await artifactsApi.openFile(props.artifact.id);
                } catch (err) {
                  console.error('Failed to open artifact file:', err);
                }
              }}
              className="flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
              title={`Open ${props.artifact.file_path}`}
            >
              <FolderGit2 className="w-3.5 h-3.5 text-cyan-400" />
              <span>Open</span>
            </button>
          )}

          <button
            onClick={handleCopy}
            className="flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
            title="Copy artifact content"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5 text-slate-400" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>

          <button
            onClick={props.onClose}
            className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      </div>

      {isHtml && viewMode === 'preview' ? (
        <div className="flex-1 flex justify-center bg-slate-950 overflow-hidden relative">
          <div
            className="h-full transition-all duration-300 border-x border-slate-800/80 shadow-2xl flex flex-col bg-white"
            style={{
              width: viewport === 'mobile' ? '375px' : viewport === 'tablet' ? '768px' : '100%',
            }}
          >
            <iframe
              srcDoc={props.artifact.content}
              title={props.artifact.title}
              className="w-full flex-1 border-0"
              sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
            />
          </div>
        </div>
      ) : isHtml && viewMode === 'code' ? (
        <div className="flex-1 overflow-y-auto p-4 select-text bg-slate-950">
          <pre className="text-[11px] font-mono leading-relaxed text-cyan-200 bg-slate-900/90 p-4 rounded-xl border border-slate-800 overflow-x-auto whitespace-pre">
            <code>{props.artifact.content}</code>
          </pre>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-4 select-text">
          <ParsedMessageContent content={props.artifact.content} />
        </div>
      )}
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
          <details
            open={Boolean(message.pending)}
            className="group mb-2.5 rounded-xl bg-slate-900/90 border border-slate-700/80 p-2.5 text-slate-300 transition-all shadow-inner"
          >
            <summary className="cursor-pointer select-none text-[11px] font-semibold uppercase tracking-wider flex items-center justify-between text-cyan-300">
              <div className="flex items-center space-x-2">
                <Sparkles className={`w-3.5 h-3.5 ${message.pending ? 'animate-spin text-cyan-400' : 'text-slate-400'}`} />
                <span>{message.pending ? 'Thinking process in progress…' : 'Thought process (completed)'}</span>
              </div>
              <div className="flex items-center space-x-2">
                {message.pending && (
                  <span className="flex items-center space-x-1.5 text-[10px] text-cyan-400 font-mono bg-cyan-950/80 px-2 py-0.5 rounded-full border border-cyan-700/50">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
                    <span>Streaming</span>
                  </span>
                )}
                <ChevronDown className="w-3.5 h-3.5 transition-transform duration-200 group-open:rotate-180 text-slate-400" />
              </div>
            </summary>
            <div className="mt-2 whitespace-pre-wrap text-[11px] font-mono leading-relaxed max-h-56 overflow-y-auto text-slate-300 bg-slate-950/90 p-2.5 rounded-lg border border-slate-800/90 selection:bg-cyan-500/30">
              {message.reasoning}
            </div>
          </details>
        )}
        {waiting && !message.reasoning ? (
          <div className="flex items-center space-x-2 py-1.5 text-slate-400">
            <Sparkles className="w-4 h-4 text-cyan-400 animate-spin" />
            <span className="text-xs animate-pulse">Pondering and formulating solution…</span>
          </div>
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

interface FamilyVariant {
  tag: string;
  sizeGb: number;
  label: string;
}

interface ModelFamily {
  id: string;
  name: string;
  variants: FamilyVariant[];
}

const POPULAR_FAMILIES: ModelFamily[] = [
  {
    id: 'qwen',
    name: 'Qwen 2.5 Coder',
    variants: [
      { tag: 'qwen2.5-coder:1.5b', sizeGb: 1.0, label: '1.5B' },
      { tag: 'qwen2.5-coder:3b', sizeGb: 2.0, label: '3B' },
      { tag: 'qwen2.5-coder:7b', sizeGb: 4.7, label: '7B' },
      { tag: 'qwen2.5-coder:14b', sizeGb: 9.0, label: '14B' },
    ],
  },
  {
    id: 'llama',
    name: 'Llama 3.2',
    variants: [
      { tag: 'llama3.2:1b', sizeGb: 1.3, label: '1B' },
      { tag: 'llama3.2:3b', sizeGb: 2.0, label: '3B' },
    ],
  },
  {
    id: 'deepseek',
    name: 'DeepSeek R1',
    variants: [
      { tag: 'deepseek-r1:1.5b', sizeGb: 1.1, label: '1.5B' },
      { tag: 'deepseek-r1:7b', sizeGb: 4.7, label: '7B' },
      { tag: 'deepseek-r1:8b', sizeGb: 5.2, label: '8B' },
      { tag: 'deepseek-r1:14b', sizeGb: 9.0, label: '14B' },
    ],
  },
  {
    id: 'mistral',
    name: 'Mistral',
    variants: [
      { tag: 'mistral:7b', sizeGb: 4.1, label: '7B' },
    ],
  },
  {
    id: 'phi',
    name: 'Phi-4',
    variants: [
      { tag: 'phi4-mini', sizeGb: 2.5, label: 'Mini' },
      { tag: 'phi4', sizeGb: 9.1, label: '14B' },
    ],
  },
];

function rateVariantFit(sizeGb: number, hw?: ModelRecommendations['hardware']): { icon: string; text: string } {
  if (!hw) return { icon: '❓', text: 'Hardware unknown' };
  const vramGb = (hw.vramBytes || 0) / (1024 * 1024 * 1024);
  const ramGb = (hw.ramBytes || 0) / (1024 * 1024 * 1024);
  if (vramGb > 0 && sizeGb * 1.15 <= vramGb) {
    return { icon: '✅', text: `Fits in GPU memory (${vramGb.toFixed(1)} GB VRAM)` };
  }
  if (ramGb > 0 && sizeGb * 1.15 <= ramGb) {
    return { icon: '⚠️', text: `Spills into system RAM (${ramGb.toFixed(1)} GB RAM)` };
  }
  return { icon: '❌', text: 'Too large for this machine' };
}

/** Local models rated for this machine, with Load/Unload, search, and 1-click downloads. */
function ModelsPanel(props: {
  data: ModelRecommendations | null;
  busyModel: string | null;
  onRefresh: () => void;
  onToggleLoaded: (m: LocalModel) => void;
  onUnloadAll?: () => void;
  connections: ServiceConnection[];
  connecting: string | null;
  connectNote: string | null;
  onToggleConnection: (c: ServiceConnection) => void;
  onClose: () => void;
}) {
  const hw = props.data?.hardware;
  const [search, setSearch] = useState('');
  const [selectedFamilyId, setSelectedFamilyId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState<string | null>(null);
  const [downloads, setDownloads] = useState<Record<string, DownloadStatus>>({});

  const handleDelete = async (modelName: string) => {
    setIsDeleting(modelName);
    try {
      await modelsApi.delete(modelName);
      setConfirmDelete(null);
      props.onRefresh();
    } catch (e) {
      console.error('Failed to delete model:', e);
    } finally {
      setIsDeleting(null);
    }
  };

  const handlePull = async (modelName: string) => {
    const trimmed = modelName.trim();
    if (!trimmed) return;
    try {
      setDownloads((prev) => ({
        ...prev,
        [trimmed]: { status: 'starting', progress: 0, step: 'Starting pull...' },
      }));
      await modelsApi.pull(trimmed);
      const res = await modelsApi.pullStatus();
      setDownloads(res.downloads);
    } catch (e) {
      console.error('Failed to start pull:', e);
      setDownloads((prev) => ({
        ...prev,
        [trimmed]: { status: 'error', progress: 0, error: String(e) },
      }));
    }
  };

  useEffect(() => {
    const hasActive = Object.values(downloads).some(
      (d) => d.status === 'starting' || d.status === 'downloading' || d.status === 'finalizing'
    );
    if (!hasActive) return;

    const interval = setInterval(async () => {
      try {
        const res = await modelsApi.pullStatus();
        setDownloads(res.downloads);
        if (Object.values(res.downloads).some((d) => d.status === 'completed')) {
          props.onRefresh();
        }
      } catch (e) {
        console.error('Error polling pull status:', e);
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [downloads, props.onRefresh]);

  const filteredModels = useMemo(() => {
    if (!props.data?.models) return [];
    const q = search.trim().toLowerCase();
    if (!q) return props.data.models;
    return props.data.models.filter((m) => m.name.toLowerCase().includes(q));
  }, [props.data?.models, search]);

  const isExactInstalled = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (props.data?.models ?? []).some((m) => m.name.toLowerCase() === q);
  }, [props.data?.models, search]);

  return (
    <div className="absolute inset-x-3 top-14 bottom-28 z-10 bg-slate-950 border border-slate-700 rounded-xl flex flex-col overflow-hidden shadow-2xl">
      <div className="px-3 py-2 text-[11px] font-semibold text-slate-400 border-b border-slate-800 flex items-center justify-between">
        <div className="flex items-center space-x-1.5">
          <Cpu className="w-3.5 h-3.5 text-cyan-400" />
          <span>Local models & library</span>
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

      {/* Model Search & Pull Bar */}
      <div className="p-2 border-b border-slate-800 bg-slate-900/50">
        <div className="relative flex items-center">
          <Search className="w-3.5 h-3.5 absolute left-2.5 text-slate-500" />
          <input
            type="text"
            placeholder="Search models or type name to download (e.g. llama3.2, mistral)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && search.trim() && !isExactInstalled) {
                handlePull(search.trim());
              }
            }}
            className="w-full bg-slate-950 border border-slate-800 focus:border-cyan-500 rounded-lg pl-8 pr-16 py-1.5 text-xs text-slate-200 placeholder-slate-500 outline-none"
          />
          {search.trim() && !isExactInstalled && (
            <button
              onClick={() => handlePull(search.trim())}
              disabled={downloads[search.trim()]?.status === 'downloading' || downloads[search.trim()]?.status === 'starting'}
              title={`Download ${search.trim()} from Ollama`}
              className="absolute right-1 px-2 py-0.5 rounded bg-cyan-700 hover:bg-cyan-600 text-[10px] text-white flex items-center space-x-1 disabled:opacity-50"
            >
              <Download className="w-3 h-3" />
              <span>Pull</span>
            </button>
          )}
        </div>

        {/* Model Family & Parameter Variant Pills */}
        <div className="mt-2 pt-1.5 border-t border-slate-800/60">
          <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
            <span className="font-semibold text-slate-400">Popular Families:</span>
            {(search || selectedFamilyId) && (
              <button
                onClick={() => {
                  setSearch('');
                  setSelectedFamilyId(null);
                }}
                className="text-slate-500 hover:text-slate-300 text-[9px]"
              >
                Clear
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1">
            {POPULAR_FAMILIES.map((fam) => {
              const isFamilyActive = selectedFamilyId === fam.id;
              return (
                <button
                  key={fam.id}
                  onClick={() => setSelectedFamilyId(isFamilyActive ? null : fam.id)}
                  className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                    isFamilyActive
                      ? 'bg-cyan-900 border border-cyan-500 text-cyan-200'
                      : 'bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {fam.name}
                </button>
              );
            })}
          </div>

          {/* Active Family Variants */}
          {selectedFamilyId && (() => {
            const fam = POPULAR_FAMILIES.find((f) => f.id === selectedFamilyId);
            if (!fam) return null;
            return (
              <div className="mt-1.5 pt-1.5 border-t border-slate-800/40 flex flex-wrap items-center gap-1.5">
                <span className="text-[9px] text-slate-500 uppercase tracking-wide font-semibold mr-0.5">Parameters:</span>
                {fam.variants.map((v) => {
                  const isInstalled = (props.data?.models ?? []).some(
                    (m) => m.name.toLowerCase() === v.tag.toLowerCase() || m.name.toLowerCase().startsWith(v.tag.toLowerCase() + ':')
                  );
                  const isDownloading = downloads[v.tag]?.status === 'downloading' || downloads[v.tag]?.status === 'starting';
                  const fit = rateVariantFit(v.sizeGb, hw);
                  const isSelected = search.toLowerCase() === v.tag.toLowerCase();

                  return (
                    <button
                      key={v.tag}
                      onClick={() => {
                        setSearch(v.tag);
                      }}
                      title={`${v.tag} (~${v.sizeGb} GB) • ${fit.text}${isInstalled ? ' (Installed)' : ''}`}
                      className={`px-1.5 py-0.5 rounded text-[10px] border transition-all flex items-center space-x-1 ${
                        isSelected
                          ? 'bg-cyan-950 border-cyan-400 text-cyan-200'
                          : isInstalled
                          ? 'bg-slate-900 border-slate-700 text-slate-300 hover:border-slate-600'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                      }`}
                    >
                      <span>{fit.icon}</span>
                      <span className="font-medium">{v.label}</span>
                      {isInstalled ? (
                        <span className="text-[9px] text-emerald-400 font-bold ml-0.5">✓</span>
                      ) : isDownloading ? (
                        <span className="text-[9px] text-cyan-400 font-mono ml-0.5">{downloads[v.tag]?.progress}%</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            );
          })()}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Active Downloads Progress Bar */}
        {Object.entries(downloads).map(([name, d]) => {
          if (d.status === 'idle') return null;
          return (
            <div key={name} className="px-3 py-2 bg-cyan-950/40 border-b border-cyan-800/40 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-cyan-200 truncate">{name}</span>
                <span className="text-[10px] text-cyan-400 font-mono">
                  {d.status === 'completed' ? '✓ Ready' : d.status === 'error' ? '❌ Error' : `${d.progress}%`}
                </span>
              </div>
              {d.step && <div className="text-[10px] text-slate-400 truncate mt-0.5">{d.step}</div>}
              {(d.status === 'downloading' || d.status === 'starting') && (
                <div className="w-full bg-slate-800 rounded-full h-1 mt-1.5 overflow-hidden">
                  <div className="bg-cyan-500 h-1 transition-all duration-300" style={{ width: `${Math.max(5, d.progress)}%` }} />
                </div>
              )}
            </div>
          );
        })}

        {props.connections.length > 0 && (
          <div className="border-b border-slate-800">
            <div className="px-3 pt-2 pb-1 text-[10px] font-semibold text-slate-400">Services (tools for the models)</div>
            {props.connections.map((c) => (
              <div key={c.service} className="px-3 py-2 flex items-center justify-between">
                <div className="min-w-0 pr-2">
                  <div className="text-xs text-slate-200 font-medium">{c.title}</div>
                  <div className="text-[10px] text-slate-500">
                    {c.connected
                      ? `Connected${c.auth === 'token' ? ' with an agent token' : ''}`
                      : 'Sign in to let the models use its tools'}
                  </div>
                </div>
                <button
                  onClick={() => props.onToggleConnection(c)}
                  disabled={props.connecting !== null}
                  title={c.connected ? 'Sign out and remove the service' : 'Opens the sign-in in your browser'}
                  className={`shrink-0 px-2 py-0.5 rounded text-[10px] disabled:opacity-40 ${
                    c.connected ? 'bg-slate-800 hover:bg-slate-700 text-amber-300' : 'bg-cyan-900/60 hover:bg-cyan-800 text-cyan-200'
                  }`}
                >
                  {props.connecting === c.service ? 'Waiting…' : c.connected ? 'Disconnect' : 'Connect'}
                </button>
              </div>
            ))}
            {props.connectNote && <div className="px-3 pb-2 text-[10px] text-cyan-300">{props.connectNote}</div>}
          </div>
        )}

        {!props.data ? (
          <div className="p-4 text-xs text-slate-500 text-center">Checking your hardware and models…</div>
        ) : (
          <>
            {(() => {
              const totalVram = hw?.vramBytes ?? 0;
              const usedVram = hw?.vramUsedBytes ?? 0;
              const pct = totalVram > 0 ? Math.min(100, Math.round((usedVram / totalVram) * 100)) : 0;
              const barColor = pct > 85 ? 'bg-rose-500' : pct > 65 ? 'bg-amber-500' : 'bg-emerald-500';
              const textColor = pct > 85 ? 'text-rose-400' : pct > 65 ? 'text-amber-400' : 'text-emerald-400';
              return (
                <div className="px-3 py-2 text-[10px] text-slate-400 border-b border-slate-800/60 flex flex-col space-y-1.5">
                  <div className="flex items-center justify-between">
                    <div>
                      {hw?.gpuName ? `${hw.gpuName}` : 'No NVIDIA GPU found'} · {formatGb(hw?.ramBytes ?? 0)} RAM
                    </div>
                    {props.data.models.some((m) => m.loaded) && (
                      <button
                        onClick={() => props.onUnloadAll?.()}
                        disabled={props.busyModel !== null}
                        title="Unload all loaded models to free VRAM immediately"
                        className="px-1.5 py-0.5 rounded text-[9px] bg-rose-950/80 hover:bg-rose-900 text-rose-300 disabled:opacity-40"
                      >
                        Unload all
                      </button>
                    )}
                  </div>
                  {totalVram > 0 && (
                    <div className="flex items-center space-x-2 pt-0.5">
                      <span className="text-[9px] text-slate-500 font-semibold uppercase tracking-wider">VRAM:</span>
                      <div className="flex-1 bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-800">
                        <div className={`h-1.5 rounded-full transition-all duration-300 ${barColor}`} style={{ width: `${Math.max(2, pct)}%` }} />
                      </div>
                      <span className={`text-[10px] font-mono font-medium ${textColor}`}>
                        {formatGb(usedVram)} / {formatGb(totalVram)} ({pct}%)
                      </span>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Prompt to download search query if not installed */}
            {search.trim() && !isExactInstalled && (
              <div className="m-2 p-2.5 bg-cyan-950/40 border border-cyan-800/50 rounded-lg flex items-center justify-between">
                <div className="min-w-0 pr-2">
                  <div className="text-xs text-cyan-200 font-medium truncate">Download "{search.trim()}"</div>
                  <div className="text-[10px] text-slate-400">Pull from Ollama library</div>
                </div>
                <button
                  onClick={() => handlePull(search.trim())}
                  disabled={downloads[search.trim()]?.status === 'downloading' || downloads[search.trim()]?.status === 'starting'}
                  className="shrink-0 px-2.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-medium flex items-center space-x-1 disabled:opacity-40"
                >
                  <Download className="w-3 h-3" />
                  <span>{downloads[search.trim()]?.status === 'downloading' ? `${downloads[search.trim()].progress}%` : 'Download'}</span>
                </button>
              </div>
            )}

            {filteredModels.length === 0 && (
              <div className="p-3 text-xs text-slate-500 text-center">
                {search ? `No installed models match "${search}".` : 'No local models installed.'}
              </div>
            )}

            <div className="divide-y divide-slate-800/60">
              {filteredModels.map((m) => (
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
                      {m.loaded && <span className="text-emerald-400 font-semibold"> · in memory ({formatGb(m.vramBytes)} on GPU)</span>}
                    </div>
                  </div>
                  <div className="flex items-center space-x-1.5 shrink-0">
                    <button
                      onClick={() => props.onToggleLoaded(m)}
                      disabled={props.busyModel !== null || (!m.loaded && m.fit === 'too_big')}
                      title={m.loaded ? 'Unload model from memory to free VRAM' : 'Load into memory now so replies start at once'}
                      className={`px-2.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
                        m.loaded
                          ? 'bg-amber-950/80 hover:bg-amber-900 border border-amber-700/60 text-amber-200'
                          : 'bg-cyan-900/60 hover:bg-cyan-800 text-cyan-200'
                      }`}
                    >
                      {props.busyModel === m.name ? '…' : m.loaded ? 'Unload' : 'Load'}
                    </button>
                    {confirmDelete === m.name ? (
                      <div className="flex items-center space-x-1 bg-rose-950/90 border border-rose-800/80 rounded px-1.5 py-0.5 text-[10px]">
                        <span className="text-rose-200 font-medium">Delete?</span>
                        <button
                          onClick={() => handleDelete(m.name)}
                          disabled={isDeleting === m.name}
                          className="text-rose-400 hover:text-white font-bold px-1"
                        >
                          {isDeleting === m.name ? '…' : 'Yes'}
                        </button>
                        <button
                          onClick={() => setConfirmDelete(null)}
                          disabled={isDeleting === m.name}
                          className="text-slate-400 hover:text-white px-1"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(m.name)}
                        disabled={m.loaded || props.busyModel !== null || isDeleting !== null}
                        title={m.loaded ? 'Unload model before deleting' : `Delete ${m.name} to free disk space`}
                        className="p-1 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 disabled:opacity-30 disabled:hover:text-slate-500 disabled:hover:bg-transparent transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
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
                      <div className="flex items-center space-x-1 shrink-0">
                        <button
                          onClick={() => handlePull(s.name)}
                          disabled={downloads[s.name]?.status === 'downloading' || downloads[s.name]?.status === 'starting'}
                          title={`Download ${s.name} into Ollama now`}
                          className="flex items-center space-x-1 px-2 py-0.5 rounded bg-cyan-900/70 hover:bg-cyan-800 text-[10px] text-cyan-200 font-medium disabled:opacity-40"
                        >
                          <Download className="w-3 h-3" />
                          <span>{downloads[s.name]?.status === 'downloading' ? `${downloads[s.name].progress}%` : 'Download'}</span>
                        </button>
                        <button
                          onClick={() => navigator.clipboard?.writeText(s.pull).catch(() => undefined)}
                          title={`Copy "${s.pull}" to clipboard`}
                          className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200"
                        >
                          <Copy className="w-3 h-3" />
                        </button>
                      </div>
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
  onToggleWindows?: () => void;
  busy: boolean;
  connected: boolean;
  onSend: (text?: string) => void;
  onStop: () => void;
  centered?: boolean;
}) {
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [recording, setRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        if (audioBlob.size > 0) {
          try {
            const res = await fetch(`${ENGINE_HTTP_URL}/api/voice/transcribe`, {
              method: 'POST',
              headers: { 'Content-Type': 'audio/wav' },
              body: audioBlob,
            });
            if (res.ok) {
              const data = await res.json();
              if (data.text) {
                props.onDraft(props.draft ? `${props.draft} ${data.text}` : data.text);
              }
            }
          } catch (err) {
            console.warn('[Voice] Transcription request failed:', err);
          }
        }
        setRecording(false);
      };

      recorder.start();
      setRecording(true);
    } catch (err) {
      console.warn('[Voice] Microphone access error:', err);
    }
  }, [props]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  // The summon shortcut (Ctrl+Shift+Space by default) brings the dock up ready to type
  useEffect(() => {
    if (!isTauri()) return;
    const unlisten = listen('summon', () => inputRef.current?.focus());
    return () => {
      unlisten.then((off) => off());
    };
  }, []);

  return (
    <div className={props.centered ? "w-full" : "mt-3"}>
      <div className="bg-slate-900/95 border border-slate-700/80 rounded-2xl p-2.5 focus-within:border-cyan-500/80 shadow-xl transition-all">
        <textarea
          ref={inputRef}
          value={props.draft}
          onChange={(e) => props.onDraft(e.target.value)}
          onInput={(e) => props.onDraft((e.target as HTMLTextAreaElement).value)}
          onKeyDown={(e) => {
            // Enter sends, Shift+Enter adds a line
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              const val = inputRef.current?.value || props.draft;
              if (val.trim()) {
                props.onSend(val);
                if (inputRef.current) inputRef.current.value = '';
              }
            }
          }}
          placeholder="How can I help you today?"
          rows={props.centered ? 3 : 2}
          className="w-full bg-transparent px-2.5 pt-1.5 text-xs text-slate-100 placeholder-slate-400 focus:outline-none resize-none select-text"
        />

        {/* Bottom Toolbar: [ + | Chat | Cowork ] ... [ Model | Mic | Send ] */}
        <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 mt-1 px-1">
          {/* Left tools: + and segmented [ Chat | Cowork ] pill */}
          <div className="flex items-center space-x-1.5">
            {props.onToggleWindows && (
              <button
                type="button"
                onClick={props.onToggleWindows}
                title="Pin desktop window (Chrome, Excel, etc.)"
                className="p-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            )}

            {/* Segmented Pill: [ Chat | Cowork ] exactly like Claude Desktop screenshot */}
            <div className="flex bg-slate-800/90 p-0.5 rounded-lg border border-slate-700/60 text-[11px]">
              <button
                type="button"
                onClick={() => props.onMode('auto')}
                className={`px-2.5 py-0.5 rounded-md font-medium transition-all ${
                  props.mode === 'auto' || props.mode === 'direct'
                    ? 'bg-slate-700 text-white shadow-xs'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Chat
              </button>
              <button
                type="button"
                onClick={() => props.onMode('antigravity')}
                className={`px-2.5 py-0.5 rounded-md font-medium transition-all ${
                  props.mode !== 'auto' && props.mode !== 'direct'
                    ? 'bg-cyan-950 text-cyan-300 border border-cyan-700/60 font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Cowork
              </button>
            </div>
          </div>

          {/* Right tools: ModelPicker, Mic, Send */}
          <div className="flex items-center space-x-1.5">
            <ModelPicker
              value={props.model}
              groups={props.modelGroups}
              localModels={props.localModels}
              onChange={props.onModel}
            />

            <button
              onClick={props.onToggleModels}
              title="Local models fit & memory"
              className="p-1 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors"
            >
              <Cpu className="w-3.5 h-3.5" />
            </button>

            <button
              type="button"
              onClick={recording ? stopRecording : startRecording}
              title={recording ? "Stop recording voice" : "Voice input (push-to-talk)"}
              className={`p-1.5 rounded-lg text-slate-300 transition-colors ${
                recording
                  ? "bg-rose-500 text-white animate-pulse"
                  : "bg-slate-800/80 hover:bg-slate-700 hover:text-white"
              }`}
            >
              {recording ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
            </button>

            {props.busy ? (
              <button
                onClick={props.onStop}
                title="Stop (Esc)"
                className="flex items-center space-x-1 bg-amber-500 hover:bg-amber-400 text-slate-950 font-semibold rounded-lg px-3 py-1 text-[11px]"
              >
                <Square className="w-3 h-3 fill-current" />
                <span>Stop</span>
              </button>
            ) : (
              <button
                onClick={() => {
                  const val = inputRef.current?.value || props.draft;
                  if (val.trim()) {
                    props.onSend(val);
                    if (inputRef.current) inputRef.current.value = '';
                  }
                }}
                disabled={!props.connected || (!props.draft.trim() && !(inputRef.current?.value || '').trim())}
                title="Send (Enter)"
                className="flex items-center space-x-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-950 font-semibold rounded-lg px-3 py-1 text-[11px] transition-colors"
              >
                <Send className="w-3 h-3" />
                <span>Send</span>
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-between text-[10px] text-slate-500 px-1">
        <div className="flex items-center">
          <ShieldAlert className="w-3 h-3 mr-1 text-amber-400/80" />
          <span>Stop anytime with <kbd className="bg-slate-800 px-1 rounded text-slate-300">Esc</kbd></span>
        </div>
        <div className="flex items-center space-x-1.5 text-slate-500">
          <span>Voice</span>
          <kbd className="bg-slate-800 px-1 rounded text-slate-300">Mic</kbd>
        </div>
      </div>
    </div>
  );
}
