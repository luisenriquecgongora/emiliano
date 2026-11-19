import React, { useMemo, useState, useEffect } from 'react';
import {
  Boxes,
  Calendar,
  Check,
  Code2,
  Filter,
  Heart,
  Megaphone,
  Palette,
  Search,
  Shield,
  Sparkles,
  Star,
  Store,
  Target,
  TrendingUp,
  Users,
  Wine,
  X,
  Zap,
  Bot,
} from 'lucide-react';
import {
  MODE_CATEGORIES,
  ModeCategory,
  SPECIALIST_MODES,
  SpecialistModeDef,
  Mode,
} from './chats';

interface ModesGalleryModalProps {
  isOpen: boolean;
  activeMode: Mode;
  onSelectMode: (mode: Mode) => void;
  onClose: () => void;
}

export default function ModesGalleryModal({
  isOpen,
  activeMode,
  onSelectMode,
  onClose,
}: ModesGalleryModalProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<ModeCategory>('all');

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  const renderIcon = (icon: string, className: string) => {
    switch (icon) {
      case 'zap': return <Zap className={className} />;
      case 'trending-up': return <TrendingUp className={className} />;
      case 'wine': return <Wine className={className} />;
      case 'calendar': return <Calendar className={className} />;
      case 'boxes': return <Boxes className={className} />;
      case 'users': return <Users className={className} />;
      case 'megaphone': return <Megaphone className={className} />;
      case 'target': return <Target className={className} />;
      case 'star': return <Star className={className} />;
      case 'heart': return <Heart className={className} />;
      case 'shield': return <Shield className={className} />;
      case 'code': return <Code2 className={className} />;
      case 'palette': return <Palette className={className} />;
      case 'bot': return <Bot className={className} />;
      default: return <Sparkles className={className} />;
    }
  };

  const filteredModes = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return SPECIALIST_MODES.filter((m) => {
      // Category filter
      if (selectedCategory !== 'all') {
        if (m.category !== selectedCategory) return false;
      }
      // Search query filter
      if (!q) return true;
      return (
        m.name.toLowerCase().includes(q) ||
        m.shortLabel.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        m.badge.toLowerCase().includes(q) ||
        m.skills.toLowerCase().includes(q) ||
        m.category.toLowerCase().includes(q)
      );
    });
  }, [searchQuery, selectedCategory]);

  const getCategoryCount = (catId: ModeCategory) => {
    if (catId === 'all') return SPECIALIST_MODES.length;
    return SPECIALIST_MODES.filter((m) => m.category === catId).length;
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/85 backdrop-blur-md animate-in fade-in duration-150 select-none">
      <div
        className="relative w-full max-w-5xl max-h-[90vh] bg-slate-900 border border-slate-700/90 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-slate-100 font-sans"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800 bg-slate-950/70 shrink-0">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-cyan-950 to-blue-950 border border-cyan-500/40 text-cyan-400 shadow-xs">
              <Store className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm sm:text-base text-slate-100 tracking-tight">
                  Domain Specialist Modes
                </span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-cyan-950/80 text-cyan-300 border border-cyan-700/60">
                  Small Business Suite
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Select an AI coworker specialist configured with dedicated personas, skills, and MCP tools for your business.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            title="Close (Esc)"
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search & Category Filter Toolbar */}
        <div className="px-5 pt-3 pb-3 border-b border-slate-800/80 bg-slate-900/60 flex flex-col gap-2.5 shrink-0">
          {/* Full-Width Search Input Bar */}
          <div className="relative w-full">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <input
              type="text"
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search all 14 modes by role, skill, or keyword (e.g. menu, cash, shifts, instagram, reviews)..."
              className="w-full bg-slate-950/70 border border-slate-700 focus:border-cyan-500/80 rounded-xl pl-10 pr-9 py-2 text-xs text-slate-100 placeholder-slate-400 focus:outline-none transition-colors shadow-inner"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white p-0.5"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Category Chips Bar */}
          <div className="flex items-center space-x-1.5 overflow-x-auto pb-0.5 text-[11px] scrollbar-none">
            {MODE_CATEGORIES.map((cat) => {
              const isSelected = selectedCategory === cat.id;
              const count = getCategoryCount(cat.id);
              return (
                <button
                  key={cat.id}
                  type="button"
                  onClick={() => setSelectedCategory(cat.id)}
                  className={`px-3 py-1.5 rounded-lg font-medium transition-all shrink-0 flex items-center space-x-1.5 border cursor-pointer ${
                    isSelected
                      ? 'bg-cyan-950 text-cyan-300 border-cyan-600/70 shadow-xs'
                      : 'bg-slate-800/70 hover:bg-slate-800 text-slate-300 hover:text-white border-slate-700/60'
                  }`}
                >
                  <span>{cat.label}</span>
                  <span className={`text-[9px] font-mono px-1.5 py-0.2 rounded-full ${
                    isSelected ? 'bg-cyan-900/80 text-cyan-200' : 'bg-slate-700 text-slate-400'
                  }`}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Modal Body: Cards Grid */}
        <div className="flex-1 overflow-y-auto p-5 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900">
          {filteredModes.length === 0 ? (
            <div className="py-16 text-center flex flex-col items-center justify-center">
              <div className="p-3 rounded-full bg-slate-800/80 text-slate-400 mb-3 border border-slate-700">
                <Search className="w-6 h-6" />
              </div>
              <div className="text-sm font-semibold text-slate-300">
                No specialist modes found
              </div>
              <p className="text-xs text-slate-500 mt-1 max-w-sm">
                No modes match "{searchQuery}" in this category. Try searching for "cash", "shifts", "menu", or "reviews".
              </p>
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('');
                  setSelectedCategory('all');
                }}
                className="mt-4 px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-400 border border-slate-700 font-medium cursor-pointer"
              >
                Clear Filters
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
              {filteredModes.map((m) => {
                const isSelected = activeMode === m.id;
                const skillTags = m.skills.split(' • ');

                return (
                  <div
                    key={m.id}
                    onClick={() => {
                      onSelectMode(m.id);
                      onClose();
                    }}
                    className={`relative group rounded-xl p-4 border transition-all cursor-pointer flex flex-col justify-between ${
                      isSelected
                        ? 'bg-slate-800/90 border-cyan-500/80 shadow-lg shadow-cyan-950/30 ring-1 ring-cyan-500/40'
                        : 'bg-slate-800/40 hover:bg-slate-800/70 border-slate-700/70 hover:border-slate-600 shadow-xs'
                    }`}
                  >
                    <div>
                      {/* Card Header: Icon + Title + Badge */}
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-center space-x-2.5">
                          <div className={`p-2 rounded-lg border shrink-0 ${m.accentClass}`}>
                            {renderIcon(m.icon, 'w-4 h-4')}
                          </div>
                          <div>
                            <div className="text-xs font-bold text-slate-100 group-hover:text-cyan-300 transition-colors">
                              {m.name}
                            </div>
                            <div className="text-[10px] text-slate-400 capitalize">
                              {m.category === 'all' ? 'Universal' : m.category} Specialist
                            </div>
                          </div>
                        </div>

                        <span className="text-[9px] px-2 py-0.5 rounded-full bg-slate-900/90 text-slate-300 border border-slate-700/80 font-medium whitespace-nowrap">
                          {m.badge}
                        </span>
                      </div>

                      {/* Description */}
                      <p className="text-[11px] text-slate-300 leading-relaxed mt-2 line-clamp-3">
                        {m.description}
                      </p>

                      {/* Skills Tags */}
                      <div className="flex flex-wrap gap-1 mt-3">
                        {skillTags.map((tag, idx) => (
                          <span
                            key={idx}
                            className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-900/80 text-slate-400 border border-slate-800"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Bottom Action Footer */}
                    <div className="mt-4 pt-3 border-t border-slate-800/70 flex items-center justify-between">
                      <span className="text-[10px] text-slate-500 font-mono">
                        id: {m.id}
                      </span>
                      {isSelected ? (
                        <div className="flex items-center space-x-1 text-emerald-400 text-[11px] font-semibold bg-emerald-950/60 px-2 py-0.5 rounded border border-emerald-800/50">
                          <Check className="w-3.5 h-3.5" />
                          <span>Active Mode</span>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="text-[11px] font-medium text-slate-300 group-hover:text-cyan-300 flex items-center space-x-1 transition-colors"
                        >
                          <span>Activate</span>
                          <span className="text-xs">→</span>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Modal Bottom Status Bar */}
        <div className="px-5 py-2.5 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-[11px] text-slate-400 shrink-0">
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_5px_#10b981]" />
            <span>Active: <strong className="text-slate-200">{SPECIALIST_MODES.find(m => m.id === activeMode)?.name || activeMode}</strong></span>
          </div>
          <div className="flex items-center space-x-3 text-slate-500 text-[10px]">
            <span>Tip: Switch modes anytime without losing chat history</span>
            <span>•</span>
            <span>{filteredModes.length} of {SPECIALIST_MODES.length} modes displayed</span>
          </div>
        </div>
      </div>
    </div>
  );
}
