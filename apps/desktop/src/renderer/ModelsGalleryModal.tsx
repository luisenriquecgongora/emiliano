import React, { useMemo, useState, useEffect } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Blocks,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock,
  Copy,
  Cpu,
  Database,
  Download,
  ExternalLink,
  Flame,
  Gauge,
  HardDrive,
  Info,
  Layers,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Trash2,
  Wrench,
  X,
  Zap,
} from 'lucide-react';
import {
  DownloadStatus,
  FIT_LABELS,
  formatGb,
  LocalModel,
  ModelChoice,
  ModelRecommendations,
  ModelSuggestion,
  modelsApi,
} from './chats';

import {
  ARCHITECTURE_RECOMMENDED_MODELS,
  ArchitectureModelPreset,
  getArchitectureFit,
  getModelKnowledge,
  ModelKnowledge,
  POPULAR_FAMILIES,
} from './modelsKnowledge';

export interface ModelsGalleryModalProps {
  isOpen: boolean;
  data: ModelRecommendations | null;
  currentModel: ModelChoice;
  busyModel: string | null;
  onRefresh: () => void;
  onSelectModel: (choice: ModelChoice) => void;
  onToggleLoaded: (m: LocalModel) => void;
  onUnloadAll?: () => void;
  onOpenCustomizeMcp?: () => void;
  onClose: () => void;
}

export default function ModelsGalleryModal({
  isOpen,
  data,
  currentModel,
  busyModel,
  onRefresh,
  onSelectModel,
  onToggleLoaded,
  onUnloadAll,
  onOpenCustomizeMcp,
  onClose,
}: ModelsGalleryModalProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTab, setSelectedTab] = useState<'all' | 'loaded' | 'recommended' | 'installed'>('all');
  const [memoryFitFilter, setMemoryFitFilter] = useState<'all' | 'fits_gpu' | 'slow' | 'too_big'>('all');
  const [selectedFamilyId, setSelectedFamilyId] = useState<string | null>(null);
  const [selectedKnowledgeTag, setSelectedKnowledgeTag] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState<string | null>(null);
  const [downloads, setDownloads] = useState<Record<string, DownloadStatus>>({});

  const hw = data?.hardware;

  // Close on Escape key (closes model card first if open, else closes modal)
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (selectedKnowledgeTag) {
          setSelectedKnowledgeTag(null);
        } else {
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, selectedKnowledgeTag, onClose]);

  // Auto-refresh models and hardware on mount and periodically while open
  useEffect(() => {
    if (!isOpen) return;
    onRefresh();
    const interval = setInterval(() => {
      onRefresh();
    }, 4000);
    return () => clearInterval(interval);
  }, [isOpen, onRefresh]);

  // Poll download progress when active downloads exist
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
          onRefresh();
        }
      } catch (e) {
        console.error('Error polling pull status:', e);
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [downloads, onRefresh]);

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

  const handleDelete = async (modelName: string) => {
    setIsDeleting(modelName);
    try {
      await modelsApi.delete(modelName);
      setConfirmDelete(null);
      onRefresh();
    } catch (e) {
      console.error('Failed to delete model:', e);
    } finally {
      setIsDeleting(null);
    }
  };

  // Loaded models currently occupying VRAM
  const loadedModels = useMemo(() => {
    return (data?.models ?? []).filter((m) => m.loaded);
  }, [data?.models]);

  // Installed models on disk
  const installedModels = useMemo(() => {
    return data?.models ?? [];
  }, [data?.models]);

  // Combined recommended presets + backend suggestions
  const recommendedPresets = useMemo(() => {
    const presets = [...ARCHITECTURE_RECOMMENDED_MODELS];
    // Incorporate engine recommendations if not already present
    if (data?.suggestions) {
      for (const s of data.suggestions) {
        if (!presets.some((p) => p.tag.toLowerCase() === s.name.toLowerCase())) {
          presets.push({
            id: s.name.replace(/[^a-zA-Z0-9]/g, '-'),
            name: s.name,
            tag: s.name,
            family: 'Custom',
            category: 'general',
            categoryLabel: 'Engine Recommended',
            sizeGb: s.sizeGb,
            minVramGb: Math.ceil(s.sizeGb * 1.15),
            minRamGb: Math.ceil(s.sizeGb * 2),
            description: s.note || 'Recommended for your system hardware profile.',
            toolsSupported: true,
            highlight: 'System Tuned',
          });
        }
      }
    }
    return presets;
  }, [data?.suggestions]);

  // Filtered lists based on search
  const q = searchQuery.toLowerCase().trim();

  const filteredLoaded = useMemo(() => {
    if (!q) return loadedModels;
    return loadedModels.filter((m) => m.name.toLowerCase().includes(q));
  }, [loadedModels, q]);

  const filteredInstalled = useMemo(() => {
    if (!q) return installedModels;
    return installedModels.filter((m) => m.name.toLowerCase().includes(q));
  }, [installedModels, q]);

  const filteredRecommended = useMemo(() => {
    return recommendedPresets.filter((p) => {
      const fit = getArchitectureFit(p.sizeGb, hw);
      if (memoryFitFilter !== 'all' && fit.fit !== memoryFitFilter) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        p.tag.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q) ||
        p.categoryLabel.toLowerCase().includes(q) ||
        p.family.toLowerCase().includes(q)
      );
    });
  }, [recommendedPresets, q, hw, memoryFitFilter]);

  const recommendedFitCounts = useMemo(() => {
    return recommendedPresets.reduce(
      (counts, preset) => {
        const fit = getArchitectureFit(preset.sizeGb, hw);
        counts[fit.fit] += 1;
        return counts;
      },
      { fits_gpu: 0, slow: 0, too_big: 0 }
    );
  }, [recommendedPresets, hw]);

  const isExactInstalled = useMemo(() => {
    if (!q) return true;
    return installedModels.some((m) => m.name.toLowerCase() === q);
  }, [installedModels, q]);

  if (!isOpen) return null;

  // VRAM Calculations
  const totalVram = hw?.vramBytes ?? 0;
  const usedVram = hw?.vramUsedBytes ?? 0;
  const vramPct = totalVram > 0 ? Math.min(100, Math.round((usedVram / totalVram) * 100)) : 0;
  const vramBarColor = vramPct > 85 ? 'bg-rose-500' : vramPct > 65 ? 'bg-amber-500' : 'bg-emerald-500';
  const vramTextColor = vramPct > 85 ? 'text-rose-400' : vramPct > 65 ? 'text-amber-400' : 'text-emerald-400';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/85 backdrop-blur-md animate-in fade-in duration-150 select-none">
      <div
        className="relative w-full max-w-5xl max-h-[92vh] bg-slate-900 border border-slate-700/90 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-slate-100 font-sans"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800 bg-slate-950/70 shrink-0">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-cyan-950 to-blue-950 border border-cyan-500/40 text-cyan-400 shadow-xs">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm sm:text-base text-slate-100 tracking-tight">
                  Local Models & Hardware Hub
                </span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-cyan-950/80 text-cyan-300 border border-cyan-700/60">
                  {hw?.gpuName ? 'GPU Accelerated' : 'CPU Inference'}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Manage local LLMs, inspect live GPU VRAM allocation, and download models optimized for your architecture.
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <button
              onClick={onRefresh}
              title="Refresh models and hardware telemetry"
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              title="Close (Esc)"
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Live Hardware & VRAM Telemetry Banner */}
        <div className="px-5 py-3 border-b border-slate-800/80 bg-slate-950/40 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
          <div className="flex items-center space-x-3">
            <div className="p-1.5 rounded-lg bg-slate-800 text-slate-300">
              <Gauge className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <div className="text-xs font-semibold text-slate-200">
                {hw?.gpuName ? hw.gpuName : 'System CPU & RAM'}
              </div>
              <div className="text-[10px] text-slate-400">
                RAM: {formatGb(hw?.ramBytes ?? 0)} · VRAM: {totalVram > 0 ? formatGb(totalVram) : 'None (System RAM fallback)'}
              </div>
            </div>
          </div>

          {/* VRAM Gauge */}
          {totalVram > 0 ? (
            <div className="flex items-center space-x-3 w-full sm:w-72">
              <div className="flex-1">
                <div className="flex items-center justify-between text-[10px] mb-1">
                  <span className="text-slate-400 font-medium">GPU VRAM</span>
                  <span className={`font-mono font-bold ${vramTextColor}`}>
                    {formatGb(usedVram)} / {formatGb(totalVram)} ({vramPct}%)
                  </span>
                </div>
                <div className="w-full bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
                  <div
                    className={`h-2 rounded-full transition-all duration-300 ${vramBarColor}`}
                    style={{ width: `${Math.max(2, vramPct)}%` }}
                  />
                </div>
              </div>
              {loadedModels.length > 0 && onUnloadAll && (
                <button
                  onClick={onUnloadAll}
                  disabled={busyModel !== null}
                  title="Unload all loaded models to free VRAM immediately"
                  className="px-2.5 py-1 rounded-lg text-[10px] font-semibold bg-rose-950/80 hover:bg-rose-900 border border-rose-700/60 text-rose-300 transition-all shrink-0 cursor-pointer disabled:opacity-40"
                >
                  Unload All
                </button>
              )}
            </div>
          ) : (
            <div className="text-[10px] text-slate-500 italic">
              No discrete NVIDIA GPU detected. Models run using unified CPU RAM.
            </div>
          )}
        </div>

        {/* Search & Tabs Toolbar */}
        <div className="px-5 pt-3 pb-3 border-b border-slate-800/80 bg-slate-900/60 flex flex-col gap-2.5 shrink-0">
          <div className="relative w-full">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <input
              type="text"
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && searchQuery.trim() && !isExactInstalled) {
                  handlePull(searchQuery.trim());
                }
              }}
              placeholder="Search installed models or type any Ollama tag to pull (e.g. qwen2.5-coder:7b, mistral, llama3.2)..."
              className="w-full bg-slate-950/70 border border-slate-700 focus:border-cyan-500/80 rounded-xl pl-10 pr-20 py-2 text-xs text-slate-100 placeholder-slate-400 focus:outline-none transition-colors shadow-inner"
            />
            {searchQuery.trim() && !isExactInstalled && (
              <button
                type="button"
                onClick={() => handlePull(searchQuery.trim())}
                disabled={downloads[searchQuery.trim()]?.status === 'downloading' || downloads[searchQuery.trim()]?.status === 'starting'}
                className="absolute right-2 top-1/2 -translate-y-1/2 px-2.5 py-1 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-[10px] font-semibold flex items-center space-x-1 disabled:opacity-50 cursor-pointer shadow-xs"
              >
                <Download className="w-3 h-3" />
                <span>Pull</span>
              </button>
            )}
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center space-x-2 text-[11px] overflow-x-auto scrollbar-none">
            <button
              onClick={() => setSelectedTab('all')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center space-x-1.5 border ${
                selectedTab === 'all'
                  ? 'bg-cyan-950 text-cyan-300 border-cyan-600/70 shadow-xs'
                  : 'bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border-slate-700/60'
              }`}
            >
              <span>Overview</span>
            </button>

            <button
              onClick={() => setSelectedTab('loaded')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center space-x-1.5 border ${
                selectedTab === 'loaded'
                  ? 'bg-cyan-950 text-cyan-300 border-cyan-600/70 shadow-xs'
                  : 'bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border-slate-700/60'
              }`}
            >
              <span className="relative flex h-2 w-2">
                {loadedModels.length > 0 && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                )}
                <span className={`relative inline-flex rounded-full h-2 w-2 ${loadedModels.length > 0 ? 'bg-emerald-500' : 'bg-slate-600'}`}></span>
              </span>
              <span>Loaded in Memory</span>
              <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-full bg-slate-700 text-slate-300">
                {loadedModels.length}
              </span>
            </button>

            <button
              onClick={() => setSelectedTab('recommended')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center space-x-1.5 border ${
                selectedTab === 'recommended'
                  ? 'bg-cyan-950 text-cyan-300 border-cyan-600/70 shadow-xs'
                  : 'bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border-slate-700/60'
              }`}
            >
              <Zap className="w-3.5 h-3.5 text-amber-400" />
              <span>Recommended for Your Architecture</span>
              <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-full bg-slate-700 text-slate-300">
                {recommendedPresets.length}
              </span>
            </button>

            <button
              onClick={() => setSelectedTab('installed')}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all cursor-pointer flex items-center space-x-1.5 border ${
                selectedTab === 'installed'
                  ? 'bg-cyan-950 text-cyan-300 border-cyan-600/70 shadow-xs'
                  : 'bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border-slate-700/60'
              }`}
            >
              <HardDrive className="w-3.5 h-3.5 text-cyan-400" />
              <span>Installed Library</span>
              <span className="text-[9px] font-mono px-1.5 py-0.2 rounded-full bg-slate-700 text-slate-300">
                {installedModels.length}
              </span>
            </button>
          </div>

          {/* Hardware-memory filters apply to recommended downloads. */}
          <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
            <span className="mr-0.5 text-slate-500 font-medium">Memory fit:</span>
            {([
              ['all', 'All models'],
              ['fits_gpu', 'Fits GPU'],
              ['slow', 'Spills to RAM'],
              ['too_big', 'Too large'],
            ] as const).map(([filter, label]) => {
              const isActive = memoryFitFilter === filter;
              const count = filter === 'all'
                ? recommendedPresets.length
                : recommendedFitCounts[filter];
              const color = filter === 'fits_gpu'
                ? 'border-emerald-700/70 text-emerald-300 bg-emerald-950/60'
                : filter === 'slow'
                ? 'border-amber-700/70 text-amber-300 bg-amber-950/60'
                : filter === 'too_big'
                ? 'border-rose-700/70 text-rose-300 bg-rose-950/60'
                : 'border-cyan-700/70 text-cyan-300 bg-cyan-950/60';

              return (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setMemoryFitFilter(filter)}
                  className={`px-2 py-1 rounded-lg border font-medium transition-colors cursor-pointer ${
                    isActive ? color : 'border-slate-700 bg-slate-800/60 text-slate-400 hover:text-slate-200 hover:border-slate-600'
                  }`}
                  title={filter === 'slow' ? 'Models that work by using both GPU VRAM and normal system RAM; they will be slower.' : undefined}
                >
                  {label} <span className="ml-0.5 opacity-70">{count}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900">
          {/* Active Downloads Progress Bar Banner */}
          {Object.entries(downloads).map(([name, d]) => {
            if (d.status === 'idle') return null;
            return (
              <div key={name} className="p-3 bg-cyan-950/60 border border-cyan-800/60 rounded-xl text-xs shadow-md">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Download className="w-4 h-4 text-cyan-400 animate-bounce" />
                    <span className="font-semibold text-cyan-200">{name}</span>
                  </div>
                  <span className="text-[10px] font-mono font-bold text-cyan-300">
                    {d.status === 'completed' ? '✓ Ready in Ollama' : d.status === 'error' ? '❌ Error' : `${d.progress}%`}
                  </span>
                </div>
                {d.step && <div className="text-[11px] text-slate-400 mt-1 truncate">{d.step}</div>}
                {(d.status === 'downloading' || d.status === 'starting') && (
                  <div className="w-full bg-slate-900 rounded-full h-1.5 mt-2 overflow-hidden border border-cyan-900/50">
                    <div
                      className="bg-gradient-to-r from-cyan-500 to-blue-500 h-1.5 transition-all duration-300"
                      style={{ width: `${Math.max(5, d.progress)}%` }}
                    />
                  </div>
                )}
              </div>
            );
          })}

          {/* SECTION 1: LOADED IN MEMORY (ACTIVE VRAM) */}
          {(selectedTab === 'all' || selectedTab === 'loaded') && (
            <div>
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center space-x-2">
                  <span className="relative flex h-2.5 w-2.5">
                    {loadedModels.length > 0 && (
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    )}
                    <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${loadedModels.length > 0 ? 'bg-emerald-500' : 'bg-slate-600'}`}></span>
                  </span>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    Loaded in Memory (Active VRAM)
                  </h3>
                </div>
                {loadedModels.length > 0 && onUnloadAll && (
                  <button
                    onClick={onUnloadAll}
                    disabled={busyModel !== null}
                    className="text-[10px] text-rose-400 hover:text-rose-300 hover:underline cursor-pointer disabled:opacity-40"
                  >
                    Unload all to free {formatGb(usedVram)}
                  </button>
                )}
              </div>

              {filteredLoaded.length === 0 ? (
                <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-center flex flex-col items-center justify-center">
                  <Cpu className="w-6 h-6 text-slate-600 mb-1.5" />
                  <div className="text-xs text-slate-400 font-medium">No models currently loaded in memory</div>
                  <p className="text-[10px] text-slate-500 mt-0.5 max-w-md">
                    GPU memory is free (0 GB VRAM consumed). Emiliano will automatically load your chosen model into memory when you chat, or you can preload one below.
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {filteredLoaded.map((m) => {
                    const isSelectedChatModel = currentModel.provider === 'ollama' && currentModel.model === m.name;
                    return (
                      <div
                        key={m.name}
                        className="p-3.5 rounded-xl bg-gradient-to-br from-emerald-950/40 to-slate-950 border border-emerald-700/50 shadow-md flex flex-col justify-between"
                      >
                        <div className="flex items-start justify-between">
                          <div className="min-w-0 pr-2">
                            <div className="flex items-center space-x-2">
                              <span className="font-bold text-xs text-emerald-200 truncate">{m.name}</span>
                              <span className="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold bg-emerald-900/80 text-emerald-300 border border-emerald-600/60">
                                Active in VRAM
                              </span>
                            </div>
                            <div className="text-[10px] text-slate-400 mt-1 flex items-center space-x-2">
                              <span>Occupying {formatGb(m.vramBytes)} VRAM</span>
                              <span>·</span>
                              <span>{m.tools ? '🔧 Tool support active' : '💬 Text only'}</span>
                            </div>
                          </div>
                          <button
                            onClick={() => onToggleLoaded(m)}
                            disabled={busyModel !== null}
                            className="px-2.5 py-1 rounded-lg text-[10px] font-semibold bg-amber-950/80 hover:bg-amber-900 border border-amber-700/60 text-amber-200 transition-colors shrink-0 cursor-pointer disabled:opacity-40"
                          >
                            {busyModel === m.name ? '…' : 'Unload'}
                          </button>
                        </div>

                        <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between">
                          <div className="flex items-center space-x-2">
                            <button
                              onClick={() => setSelectedKnowledgeTag(m.name)}
                              className="text-[10px] font-semibold text-cyan-400 hover:text-cyan-300 hover:underline flex items-center space-x-1 cursor-pointer"
                            >
                              <Info className="w-3 h-3" />
                              <span>Model Card</span>
                            </button>
                            <span className="text-[10px] text-slate-500">
                              {isSelectedChatModel ? '· ⭐ Active Chat Model' : '· Ready for instant responses'}
                            </span>
                          </div>
                          {!isSelectedChatModel && (
                            <button
                              onClick={() => onSelectModel({ provider: 'ollama', model: m.name })}
                              className="text-[10px] font-semibold text-cyan-400 hover:text-cyan-300 hover:underline flex items-center space-x-1 cursor-pointer"
                            >
                              <span>Use for Chat</span>
                              <ArrowRight className="w-3 h-3" />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* SECTION 2: RECOMMENDED FOR YOUR ARCHITECTURE */}
          {(selectedTab === 'all' || selectedTab === 'recommended') && (
            <div>
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center space-x-2">
                  <Zap className="w-3.5 h-3.5 text-amber-400" />
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    Recommended for Your Architecture
                  </h3>
                </div>
                <span className="text-[10px] text-slate-400">
                  Rated specifically for {hw?.gpuName ? `${hw.gpuName} (${formatGb(totalVram)} VRAM)` : 'your CPU/RAM'}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {filteredRecommended.map((p) => {
                  const fit = getArchitectureFit(p.sizeGb, hw);
                  const knowledge = getModelKnowledge(p.tag);
                  const isInstalled = installedModels.some(
                    (m) => m.name.toLowerCase() === p.tag.toLowerCase() || m.name.toLowerCase().startsWith(p.tag.toLowerCase() + ':')
                  );
                  const isLoaded = loadedModels.some(
                    (m) => m.name.toLowerCase() === p.tag.toLowerCase() || m.name.toLowerCase().startsWith(p.tag.toLowerCase() + ':')
                  );
                  const isDownloading = downloads[p.tag]?.status === 'downloading' || downloads[p.tag]?.status === 'starting';
                  const isSelectedChatModel = currentModel.provider === 'ollama' && currentModel.model === p.tag;

                  return (
                    <div
                      key={p.id}
                      className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800 hover:border-slate-700/80 transition-all flex flex-col justify-between shadow-sm group"
                    >
                      <div>
                        {/* Header & Badges */}
                        <div className="flex items-start justify-between gap-1 mb-1.5">
                          <div>
                            <div className="text-xs font-bold text-slate-100 group-hover:text-cyan-300 transition-colors">
                              {p.name}
                            </div>
                            <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                              {p.tag} · ~{p.sizeGb} GB
                            </div>
                          </div>
                          {p.highlight && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-cyan-950 text-cyan-300 border border-cyan-700/50 shrink-0">
                              {p.highlight}
                            </span>
                          )}
                        </div>

                        {/* Fit Rating Badge */}
                        <div className={`mt-1 inline-flex items-center space-x-1 px-2 py-0.5 rounded text-[9px] font-semibold border ${fit.badgeClass}`}>
                          <span>{fit.icon}</span>
                          <span>{fit.label}</span>
                        </div>

                        {/* Description */}
                        <p className="text-[11px] text-slate-400 mt-2 leading-relaxed line-clamp-2">
                          {p.description}
                        </p>

                        {/* Good For quick tags */}
                        <div className="mt-2.5 pt-2 border-t border-slate-800/80">
                          <div className="text-[10px] font-semibold text-cyan-300 mb-1 flex items-center space-x-1">
                            <span>🎯 Good for:</span>
                          </div>
                          <ul className="space-y-0.5">
                            {knowledge.bestFor.slice(0, 2).map((bf, idx) => (
                              <li key={idx} className="text-[10.5px] text-slate-300 flex items-start space-x-1 leading-snug">
                                <span className="text-cyan-400 font-bold shrink-0">·</span>
                                <span className="line-clamp-1">{bf}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>

                      {/* Card Action Controls */}
                      <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between">
                        <button
                          onClick={() => setSelectedKnowledgeTag(p.tag)}
                          title="View full Model Card with benchmarks, architecture fit, and best-use cases"
                          className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-slate-800/90 hover:bg-slate-800 hover:text-cyan-300 text-slate-300 border border-slate-700/80 flex items-center space-x-1 cursor-pointer transition-colors"
                        >
                          <Info className="w-3 h-3 text-cyan-400" />
                          <span>Model Card</span>
                        </button>

                        <div className="flex items-center space-x-1.5">
                          {isInstalled ? (
                            <>
                              <span className="text-[10px] font-bold text-emerald-400 flex items-center mr-1">
                                <Check className="w-3 h-3 mr-0.5" /> Installed
                              </span>
                              {!isLoaded ? (
                                <button
                                  onClick={() => {
                                    const match = installedModels.find((m) => m.name.toLowerCase().includes(p.tag.toLowerCase()));
                                    if (match) onToggleLoaded(match);
                                  }}
                                  disabled={busyModel !== null}
                                  className="px-2 py-0.5 rounded bg-cyan-900/60 hover:bg-cyan-800 text-[10px] text-cyan-200 font-medium cursor-pointer"
                                >
                                  Load
                                </button>
                              ) : null}
                              {!isSelectedChatModel && (
                                <button
                                  onClick={() => onSelectModel({ provider: 'ollama', model: p.tag })}
                                  className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-[10px] text-slate-300 font-medium cursor-pointer"
                                >
                                  Select
                                </button>
                              )}
                            </>
                          ) : (
                            <button
                              onClick={() => handlePull(p.tag)}
                              disabled={isDownloading}
                              className="px-3 py-1 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-[10px] font-semibold flex items-center space-x-1 cursor-pointer disabled:opacity-50 shadow-xs"
                            >
                              <Download className="w-3 h-3" />
                              <span>{isDownloading ? `${downloads[p.tag]?.progress}%` : 'Download'}</span>
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* SECTION 3: INSTALLED MODELS ON DISK */}
          {(selectedTab === 'all' || selectedTab === 'installed') && (
            <div>
              <div className="flex items-center justify-between mb-2.5">
                <div className="flex items-center space-x-2">
                  <HardDrive className="w-3.5 h-3.5 text-cyan-400" />
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                    Installed Local Models ({installedModels.length})
                  </h3>
                </div>
                <span className="text-[10px] text-slate-400">
                  Stored locally in your Ollama library
                </span>
              </div>

              {filteredInstalled.length === 0 ? (
                <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 text-center text-xs text-slate-500">
                  {searchQuery ? `No installed models match "${searchQuery}".` : 'No models installed yet. Pull one from recommendations above!'}
                </div>
              ) : (
                <div className="divide-y divide-slate-800/70 border border-slate-800 rounded-xl bg-slate-950/50 overflow-hidden">
                  {filteredInstalled.map((m) => {
                    const isSelectedChatModel = currentModel.provider === 'ollama' && currentModel.model === m.name;
                    const installedKnowledge = getModelKnowledge(m.name);
                    return (
                      <div key={m.name} className="p-3 flex items-center justify-between hover:bg-slate-900/40 transition-colors">
                        <div className="min-w-0 pr-3">
                          <div className="flex items-center space-x-2">
                            <span className="text-xs font-semibold text-slate-100 truncate">{m.name}</span>
                            {m.recommended && (
                              <span className="px-1.5 py-0.2 rounded text-[9px] bg-cyan-950 text-cyan-300 border border-cyan-700/60 font-semibold">
                                Recommended
                              </span>
                            )}
                            {m.loaded && (
                              <span className="px-1.5 py-0.2 rounded text-[9px] bg-emerald-950 text-emerald-300 border border-emerald-700/60 font-semibold">
                                In VRAM ({formatGb(m.vramBytes)})
                              </span>
                            )}
                            {isSelectedChatModel && (
                              <span className="px-1.5 py-0.2 rounded text-[9px] bg-amber-950 text-amber-300 border border-amber-700/60 font-semibold">
                                Active Chat Model
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] text-slate-400 mt-0.5 flex flex-wrap items-center gap-1.5">
                            <span>{formatGb(m.sizeBytes)} on disk</span>
                            <span>·</span>
                            <span>{FIT_LABELS[m.fit]?.text || m.fit}</span>
                            <span>·</span>
                            <span>{m.tools === null ? 'Tool support unknown' : m.tools ? '🔧 Supports tools' : '💬 Text only'}</span>
                            <span>·</span>
                            <span className="text-cyan-300 font-medium">🎯 {installedKnowledge.bestFor[0]?.split(',')[0]}</span>
                          </div>
                        </div>

                        <div className="flex items-center space-x-2 shrink-0">
                          <button
                            onClick={() => setSelectedKnowledgeTag(m.name)}
                            title="View full Model Card with benchmarks, architecture fit, and best-use cases"
                            className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-slate-800 hover:bg-slate-700 hover:text-cyan-300 text-slate-300 border border-slate-700 flex items-center space-x-1 cursor-pointer transition-colors"
                          >
                            <Info className="w-3 h-3 text-cyan-400" />
                            <span>Model Card</span>
                          </button>

                          {!isSelectedChatModel && (
                            <button
                              onClick={() => onSelectModel({ provider: 'ollama', model: m.name })}
                              className="px-2.5 py-1 rounded-lg text-[10px] font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors cursor-pointer"
                            >
                              Select
                            </button>
                          )}

                          <button
                            onClick={() => onToggleLoaded(m)}
                            disabled={busyModel !== null || (!m.loaded && m.fit === 'too_big')}
                            className={`px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-colors cursor-pointer ${
                              m.loaded
                                ? 'bg-amber-950/80 hover:bg-amber-900 border border-amber-700/60 text-amber-200'
                                : 'bg-cyan-900/60 hover:bg-cyan-800 text-cyan-200'
                            }`}
                          >
                            {busyModel === m.name ? '…' : m.loaded ? 'Unload' : 'Load'}
                          </button>

                          {confirmDelete === m.name ? (
                            <div className="flex items-center space-x-1 bg-rose-950/90 border border-rose-800 rounded-lg px-2 py-0.5 text-[10px]">
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
                              disabled={m.loaded || busyModel !== null || isDeleting !== null}
                              title={m.loaded ? 'Unload model before deleting' : `Delete ${m.name} from disk`}
                              className="p-1 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 disabled:opacity-30 cursor-pointer transition-colors"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* SECTION 4: POPULAR MODEL FAMILIES & EXPLORER */}
          <div className="p-4 rounded-xl bg-slate-950/40 border border-slate-800/80">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-300 mb-2">
              <div className="flex items-center space-x-1.5">
                <Layers className="w-3.5 h-3.5 text-cyan-400" />
                <span>Explore Popular Families & Parameter Sizes</span>
              </div>
              {selectedFamilyId && (
                <button
                  onClick={() => setSelectedFamilyId(null)}
                  className="text-[10px] text-slate-400 hover:text-white cursor-pointer"
                >
                  Clear Selection
                </button>
              )}
            </div>

            <div className="flex flex-wrap gap-1.5">
              {POPULAR_FAMILIES.map((fam) => {
                const isFamilyActive = selectedFamilyId === fam.id;
                return (
                  <button
                    key={fam.id}
                    onClick={() => setSelectedFamilyId(isFamilyActive ? null : fam.id)}
                    className={`px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all cursor-pointer ${
                      isFamilyActive
                        ? 'bg-cyan-900 border border-cyan-500 text-cyan-100 shadow-xs'
                        : 'bg-slate-900 border border-slate-800 hover:border-slate-700 text-slate-300 hover:text-white'
                    }`}
                  >
                    {fam.name}
                  </button>
                );
              })}
            </div>

            {selectedFamilyId && (() => {
              const fam = POPULAR_FAMILIES.find((f) => f.id === selectedFamilyId);
              if (!fam) return null;
              return (
                <div className="mt-3 pt-2.5 border-t border-slate-800/60 flex flex-wrap items-center gap-2">
                  <span className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">
                    Available Sizes:
                  </span>
                  {fam.variants.map((v) => {
                    const isInstalled = installedModels.some(
                      (m) => m.name.toLowerCase() === v.tag.toLowerCase() || m.name.toLowerCase().startsWith(v.tag.toLowerCase() + ':')
                    );
                    const fit = getArchitectureFit(v.sizeGb, hw);
                    const isDownloading = downloads[v.tag]?.status === 'downloading' || downloads[v.tag]?.status === 'starting';

                    return (
                      <div
                        key={v.tag}
                        className="flex items-center space-x-1.5 px-2 py-1 rounded-lg bg-slate-900 border border-slate-800 text-[10px]"
                      >
                        <span title={fit.label}>{fit.icon}</span>
                        <span className="font-semibold text-slate-200">{v.label} (~{v.sizeGb} GB)</span>
                        {isInstalled ? (
                          <span className="text-emerald-400 font-bold ml-1">✓ Installed</span>
                        ) : isDownloading ? (
                          <span className="text-cyan-400 font-mono ml-1">{downloads[v.tag]?.progress}%</span>
                        ) : (
                          <button
                            onClick={() => handlePull(v.tag)}
                            className="ml-1 text-cyan-400 hover:text-cyan-300 font-semibold cursor-pointer hover:underline"
                          >
                            Pull
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })()}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-5 py-3 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-xs text-slate-400 shrink-0">
          <div className="flex items-center space-x-2 truncate">
            <Blocks className="w-4 h-4 text-cyan-400 shrink-0" />
            <span className="text-[11px] text-slate-400 truncate">
              External MCP services & business tools are configured in Customize
            </span>
          </div>

          <div className="flex items-center space-x-3 shrink-0">
            {onOpenCustomizeMcp && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onOpenCustomizeMcp();
                }}
                className="text-cyan-400 hover:text-cyan-300 font-medium hover:underline text-[11px] cursor-pointer"
              >
                Open Customize MCP →
              </button>
            )}
            <button
              onClick={onClose}
              className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold cursor-pointer transition-colors"
            >
              Done
            </button>
          </div>
        </div>

        {/* Model Card Sheet / Detailed Information Overlay */}
        {selectedKnowledgeTag && (() => {
          const knowledge = getModelKnowledge(selectedKnowledgeTag);
          const installedMatch = installedModels.find(
            (m) =>
              m.name.toLowerCase() === selectedKnowledgeTag.toLowerCase() ||
              m.name.toLowerCase().startsWith(selectedKnowledgeTag.toLowerCase() + ':') ||
              selectedKnowledgeTag.toLowerCase().startsWith(m.name.toLowerCase() + ':')
          );
          const loadedMatch = loadedModels.find(
            (m) =>
              m.name.toLowerCase() === selectedKnowledgeTag.toLowerCase() ||
              m.name.toLowerCase().startsWith(selectedKnowledgeTag.toLowerCase() + ':') ||
              selectedKnowledgeTag.toLowerCase().startsWith(m.name.toLowerCase() + ':')
          );
          const presetMatch = recommendedPresets.find(
            (p) =>
              p.tag.toLowerCase() === selectedKnowledgeTag.toLowerCase() ||
              selectedKnowledgeTag.toLowerCase().startsWith(p.tag.toLowerCase()) ||
              p.name.toLowerCase() === selectedKnowledgeTag.toLowerCase()
          );
          const sizeGb = presetMatch?.sizeGb || (installedMatch ? installedMatch.sizeBytes / (1024 * 1024 * 1024) : 4.0);
          const isInstalled = !!installedMatch;
          const isLoaded = !!loadedMatch;
          const isSelectedChatModel =
            currentModel.provider === 'ollama' &&
            (currentModel.model.toLowerCase() === selectedKnowledgeTag.toLowerCase() ||
              (installedMatch && currentModel.model === installedMatch.name));
          const isDownloading =
            downloads[selectedKnowledgeTag]?.status === 'downloading' ||
            downloads[selectedKnowledgeTag]?.status === 'starting';
          const downloadProgress = downloads[selectedKnowledgeTag]?.progress;

          // Hardware calculations
          const totalVramGb = (hw?.vramBytes || 0) / (1024 * 1024 * 1024);
          const totalRamGb = (hw?.ramBytes || 0) / (1024 * 1024 * 1024);
          const requiredGb = sizeGb * 1.15;
          const fitsGpu = totalVramGb > 0 && requiredGb <= totalVramGb;
          const spillsRam = totalVramGb > 0 && !fitsGpu && requiredGb <= totalVramGb + totalRamGb * 0.5;

          let perfHeadline = '';
          let speedEstimate = '';
          let perfDetails = '';
          let fitBadgeColor = '';
          let fitIcon = '';

          if (fitsGpu) {
            perfHeadline = 'Full High-Speed GPU Acceleration';
            speedEstimate = '~50 – 85 tokens/sec';
            perfDetails = `Entire model weights (~${sizeGb.toFixed(1)} GB) fit completely inside your ${
              hw?.gpuName || 'GPU'
            } VRAM (${totalVramGb.toFixed(1)} GB). Near-zero latency, instant tool execution, and zero CPU offload penalty.`;
            fitBadgeColor = 'bg-emerald-950 text-emerald-300 border-emerald-700/70';
            fitIcon = '⚡';
          } else if (spillsRam) {
            perfHeadline = 'Partial VRAM + System RAM Offloading';
            speedEstimate = '~12 – 25 tokens/sec';
            perfDetails = `Model requires ~${requiredGb.toFixed(1)} GB. Layers will split between ${totalVramGb.toFixed(
              1
            )} GB GPU VRAM and ${totalRamGb.toFixed(
              1
            )} GB System RAM. Fully functional with moderate generation latency.`;
            fitBadgeColor = 'bg-amber-950 text-amber-300 border-amber-700/70';
            fitIcon = '⚠️';
          } else if (totalVramGb > 0) {
            perfHeadline = 'Exceeds High-Speed Memory Capacity';
            speedEstimate = '~3 – 8 tokens/sec';
            perfDetails = `Model requires ~${requiredGb.toFixed(
              1
            )} GB, which exceeds available high-speed memory and will cause disk paging. Consider running a more compact parameter variant (e.g. 3B or Mini).`;
            fitBadgeColor = 'bg-rose-950 text-rose-300 border-rose-700/70';
            fitIcon = '❌';
          } else {
            perfHeadline = 'CPU Inference (Unified System Memory)';
            speedEstimate = '~10 – 20 tokens/sec';
            perfDetails = `Runs locally using multicore CPU execution and ${totalRamGb.toFixed(
              1
            )} GB System RAM. Fully functional for everyday chat and workflows.`;
            fitBadgeColor = 'bg-slate-800 text-slate-300 border-slate-700';
            fitIcon = '💻';
          }

          return (
            <div
              className="fixed inset-0 z-60 flex items-center justify-center p-3 sm:p-6 bg-slate-950/80 backdrop-blur-md animate-in fade-in duration-150 select-none"
              onClick={() => setSelectedKnowledgeTag(null)}
            >
              <div
                className="relative w-full max-w-3xl max-h-[92vh] bg-slate-900 border border-slate-700/90 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-slate-100 font-sans"
                onClick={(e) => e.stopPropagation()}
              >
                {/* Card Modal Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800 bg-slate-950/70 shrink-0">
                  <div className="flex items-center space-x-3">
                    <div className="p-2.5 rounded-xl bg-gradient-to-br from-cyan-950 to-blue-950 border border-cyan-500/40 text-cyan-400 shadow-xs">
                      <BookOpen className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-base text-slate-100 tracking-tight">
                          {knowledge.displayName}
                        </span>
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-cyan-950/80 text-cyan-300 border border-cyan-700/60">
                          {knowledge.tag}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 mt-1 text-[11px] text-slate-400">
                        <span>By {knowledge.author}</span>
                        <span>·</span>
                        <span className="px-1.5 py-0.2 rounded bg-slate-800 border border-slate-700 text-slate-300 font-mono text-[10px]">
                          {knowledge.license}
                        </span>
                        <span>·</span>
                        <span className="px-1.5 py-0.2 rounded bg-slate-800 border border-slate-700 text-cyan-300 font-mono text-[10px]">
                          {knowledge.contextWindow}
                        </span>
                        <span>·</span>
                        <span className="text-slate-300 font-medium">~{sizeGb.toFixed(1)} GB</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => setSelectedKnowledgeTag(null)}
                    className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                {/* Specialty Headline Banner */}
                <div className="px-5 py-2.5 bg-gradient-to-r from-cyan-950/80 via-slate-900 to-blue-950/80 border-b border-cyan-800/40 flex items-center space-x-2 text-xs text-cyan-200 shrink-0">
                  <Sparkles className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span className="font-medium">{knowledge.specialtyHeadline}</span>
                </div>

                {/* Card Scrollable Body */}
                <div className="flex-1 overflow-y-auto p-5 space-y-5 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900">
                  {/* SECTION 1: WHAT IS IT GOOD FOR? */}
                  <div>
                    <div className="flex items-center space-x-2 mb-2.5">
                      <span className="text-sm">🎯</span>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                        What Is It Good For? (Best Use Cases)
                      </h4>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                      {knowledge.bestFor.map((item, idx) => (
                        <div
                          key={idx}
                          className="p-3 rounded-xl bg-slate-950/60 border border-slate-800 flex items-start space-x-2.5"
                        >
                          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                          <span className="text-xs text-slate-200 leading-relaxed font-normal">{item}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* SECTION 2: HARDWARE & ESTIMATED PERFORMANCE */}
                  <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center space-x-2">
                        <Gauge className="w-4 h-4 text-cyan-400" />
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                          Estimated Performance on Your Machine
                        </h4>
                      </div>
                      <div className={`px-2 py-0.5 rounded text-[10px] font-semibold border flex items-center space-x-1 ${fitBadgeColor}`}>
                        <span>{fitIcon}</span>
                        <span>{perfHeadline}</span>
                      </div>
                    </div>

                    <div className="text-xs text-slate-300 leading-relaxed mt-1">
                      {perfDetails}
                    </div>

                    <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex flex-wrap items-center justify-between text-xs text-slate-400 gap-2">
                      <div className="flex items-center space-x-2">
                        <Cpu className="w-3.5 h-3.5 text-slate-400" />
                        <span>Detected: <strong className="text-slate-200">{hw?.gpuName || 'System CPU'}</strong> ({totalVramGb > 0 ? `${formatGb(hw?.vramBytes || 0)} VRAM` : `${formatGb(hw?.ramBytes || 0)} RAM`})</span>
                      </div>
                      <div className="flex items-center space-x-2 font-mono">
                        <span className="text-slate-400">Expected Speed:</span>
                        <span className="px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 font-bold border border-cyan-700/50">
                          {speedEstimate}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* SECTION 3: BENCHMARKS & CAPABILITY PROFILE */}
                  <div>
                    <div className="flex items-center space-x-2 mb-2.5">
                      <Activity className="w-4 h-4 text-cyan-400" />
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                        Capability & Benchmark Profile
                      </h4>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                      <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 flex flex-col justify-between">
                        <div className="text-[10px] text-slate-400 font-medium">Coding & Automation</div>
                        <div className="text-base font-bold text-cyan-400 mt-1 font-mono">
                          {knowledge.scores.coding}%
                        </div>
                        <div className="w-full bg-slate-900 rounded-full h-1 mt-1 overflow-hidden">
                          <div
                            className="bg-cyan-500 h-1 rounded-full"
                            style={{ width: `${knowledge.scores.coding}%` }}
                          />
                        </div>
                      </div>

                      <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 flex flex-col justify-between">
                        <div className="text-[10px] text-slate-400 font-medium">Tool Calling & MCP</div>
                        <div className="text-base font-bold text-emerald-400 mt-1 font-mono">
                          {knowledge.scores.toolCalling}%
                        </div>
                        <div className="w-full bg-slate-900 rounded-full h-1 mt-1 overflow-hidden">
                          <div
                            className="bg-emerald-500 h-1 rounded-full"
                            style={{ width: `${knowledge.scores.toolCalling}%` }}
                          />
                        </div>
                      </div>

                      <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 flex flex-col justify-between">
                        <div className="text-[10px] text-slate-400 font-medium">Deep Reasoning</div>
                        <div className="text-base font-bold text-violet-400 mt-1 font-mono">
                          {knowledge.scores.reasoning}%
                        </div>
                        <div className="w-full bg-slate-900 rounded-full h-1 mt-1 overflow-hidden">
                          <div
                            className="bg-violet-500 h-1 rounded-full"
                            style={{ width: `${knowledge.scores.reasoning}%` }}
                          />
                        </div>
                      </div>

                      <div className="p-2.5 rounded-xl bg-slate-950/60 border border-slate-800 flex flex-col justify-between">
                        <div className="text-[10px] text-slate-400 font-medium">Latency & Speed</div>
                        <div className="text-base font-bold text-amber-400 mt-1 font-mono">
                          {knowledge.scores.speed}%
                        </div>
                        <div className="w-full bg-slate-900 rounded-full h-1 mt-1 overflow-hidden">
                          <div
                            className="bg-amber-500 h-1 rounded-full"
                            style={{ width: `${knowledge.scores.speed}%` }}
                          />
                        </div>
                      </div>
                    </div>

                    {/* Strengths Highlights */}
                    <div className="space-y-1.5">
                      {knowledge.strengths.map((str, idx) => (
                        <div
                          key={idx}
                          className="px-3 py-2 rounded-lg bg-slate-950/40 border border-slate-800/80 flex items-start space-x-2 text-xs text-slate-300"
                        >
                          <Sparkles className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-0.5" />
                          <span>{str}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* SECTION 4: HARDWARE & OPERATIONAL TRADEOFFS */}
                  {knowledge.considerations.length > 0 && (
                    <div className="p-3.5 rounded-xl bg-amber-950/30 border border-amber-800/50">
                      <div className="flex items-center space-x-2 text-xs font-bold text-amber-300 mb-1.5">
                        <AlertTriangle className="w-4 h-4 text-amber-400" />
                        <span>Tradeoffs & What to Watch Out For</span>
                      </div>
                      <ul className="space-y-1 text-xs text-amber-200/90 leading-relaxed">
                        {knowledge.considerations.map((c, idx) => (
                          <li key={idx} className="flex items-start space-x-1.5">
                            <span className="text-amber-400 font-bold">·</span>
                            <span>{c}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {/* Modal Footer Actions */}
                <div className="px-5 py-3 border-t border-slate-800 bg-slate-950/90 flex items-center justify-between shrink-0">
                  <div className="flex items-center space-x-2 text-xs">
                    {isSelectedChatModel ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-950 text-amber-300 border border-amber-700/60">
                        ⭐ Active Chat Model
                      </span>
                    ) : isLoaded ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-950 text-emerald-300 border border-emerald-700/60">
                        🟢 In VRAM (Ready)
                      </span>
                    ) : isInstalled ? (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                        💾 Stored Locally
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-cyan-950 text-cyan-300 border border-cyan-800">
                        ☁️ Available in Ollama
                      </span>
                    )}
                  </div>

                  <div className="flex items-center space-x-2">
                    {!isInstalled ? (
                      <button
                        onClick={() => {
                          handlePull(knowledge.tag);
                        }}
                        disabled={isDownloading}
                        className="px-4 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold flex items-center space-x-1.5 cursor-pointer disabled:opacity-50 shadow-sm"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <span>{isDownloading ? `Downloading ${downloadProgress}%` : `Download (~${sizeGb.toFixed(1)} GB)`}</span>
                      </button>
                    ) : (
                      <>
                        <button
                          onClick={() => {
                            if (installedMatch) onToggleLoaded(installedMatch);
                          }}
                          disabled={busyModel !== null}
                          className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors cursor-pointer ${
                            isLoaded
                              ? 'bg-amber-950/90 hover:bg-amber-900 border border-amber-700/70 text-amber-200'
                              : 'bg-cyan-900/70 hover:bg-cyan-800 text-cyan-200'
                          }`}
                        >
                          {busyModel === (installedMatch?.name || knowledge.tag) ? '…' : isLoaded ? 'Unload VRAM' : 'Load into VRAM'}
                        </button>

                        {!isSelectedChatModel && (
                          <button
                            onClick={() => {
                              onSelectModel({ provider: 'ollama', model: installedMatch ? installedMatch.name : knowledge.tag });
                            }}
                            className="px-3.5 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold cursor-pointer shadow-sm flex items-center space-x-1"
                          >
                            <span>Use for Chat</span>
                            <ArrowRight className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </>
                    )}

                    <button
                      onClick={() => setSelectedKnowledgeTag(null)}
                      className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold cursor-pointer transition-colors"
                    >
                      Close
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
