// Client for the engine's saved chats API (see packages/engine/emiliano/history/api.py)

import type { ArtifactPayload } from '@emiliano/protocol';

export const ENGINE_HTTP_URL = 'http://127.0.0.1:8765';
export const CHAT_WS_URL = 'ws://127.0.0.1:8765/api/chat';

export interface ChatSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ToolCallRecord {
  tool: string;
  mcp_server?: string;
  tool_name?: string;
  args?: Record<string, any>;
  result?: string;
  duration_s?: number;
  status?: 'ok' | 'error' | string;
}

export interface TraceSpanRecord {
  name: string;
  trace_id?: string;
  span_id?: string;
  parent_span_id?: string;
  duration_ms?: number;
  status?: string;
  error?: string;
  attributes?: Record<string, any>;
}

export interface TaskTraceRecord {
  id: string;
  goal: string;
  route?: string;
  model?: string;
  duration_s?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  spans?: TraceSpanRecord[];
  executed_tools?: ToolCallRecord[];
  guardrails?: any[];
  attempts?: any[];
}

export interface ResponseMetrics {
  total_duration_s: number;
  formatted_duration: string;
  ttft_ms?: number;
  tokens_per_second?: number;
  completion_tokens?: number;
  prompt_tokens?: number;
  thinking_duration_s?: number;
  generation_duration_s?: number;
  tool_duration_s?: number;
  tools_count?: number;
  route?: string;
  status?: string;
  tool_calls?: ToolCallRecord[];
  trace?: TaskTraceRecord;
}

export interface ChatMessage {
  id: number | string;
  role: 'user' | 'assistant';
  content: string;
  created_at?: string;
  // Present while a reply streams in, and kept for display afterwards
  reasoning?: string;
  route?: string;
  pending?: boolean;
  artifacts?: ArtifactPayload[];
  metrics?: ResponseMetrics;
  tool_calls?: ToolCallRecord[];
}

export interface ChatDetail extends ChatSummary {
  messages: ChatMessage[];
}

/** An agent asks before running a tool (ACP session/request_permission, relayed by the engine). */
export interface PermissionOption {
  optionId: string;
  name: string;
  kind: 'allow_once' | 'allow_always' | 'reject_once' | 'reject_always';
}

export interface PermissionRequest {
  request_id: string;
  title: string;
  kind: string;
  options: PermissionOption[];
}

export interface ContextMetrics {
  chat_id: string;
  total_tokens: number;
  history_tokens: number;
  system_tokens: number;
  persistent_tokens: number;
  available_tokens: number;
  max_tokens: number;
  usage_percentage: number;
  message_count: number;
  status: 'GOOD' | 'MODERATE' | 'HIGH' | 'CRITICAL';
}

export interface CompactResult {
  status: 'compacted' | 'noop';
  tokens_saved?: number;
  message_count?: number;
  summary?: string;
  message?: string;
}

export const MODE_CATEGORIES = [
  { id: 'all', label: 'All Modes' },
  { id: 'hospitality', label: 'Hospitality & F&B' },
  { id: 'finance', label: 'Finance & Stock' },
  { id: 'growth', label: 'Marketing & Sales' },
  { id: 'operations', label: 'Staff & Ops' },
  { id: 'tech', label: 'Tech & Creative' },
] as const;

export type ModeCategory = (typeof MODE_CATEGORIES)[number]['id'];

/** The dock's mode dropdown; values match the engine's resolve_mode(). */
export interface SpecialistModeDef {
  id: string;
  name: string;
  shortLabel: string;
  category: ModeCategory;
  description: string;
  badge: string;
  skills: string;
  icon: string;
  color: string;
  accentClass: string;
  featured?: boolean;
}

export const SPECIALIST_MODES: SpecialistModeDef[] = [
  {
    id: 'auto',
    name: 'General Coworker',
    shortLabel: 'General',
    category: 'all',
    description: 'Universal coworker with autonomous routing across all MCP tools, local models, and online agents.',
    badge: 'Universal',
    skills: 'Auto Routing • All MCPs • Multi-Agent',
    icon: 'zap',
    color: 'from-amber-500/20 to-orange-500/20 text-amber-400 border-amber-500/40',
    accentClass: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
    featured: true,
  },
  {
    id: 'financial',
    name: 'Financial & Business Ops',
    shortLabel: 'Financial',
    category: 'finance',
    description: 'Hospitality CFO mode: PlaatoOS financial analytics, POS cash boxes, safe reconciliation, P&L, and KPI metrics.',
    badge: 'PlaatoOS Finances',
    skills: 'PlaatoOS MCP • Safe Reconciliation • Cash Boxes • P&L',
    icon: 'trending-up',
    color: 'from-emerald-500/20 to-teal-500/20 text-emerald-400 border-emerald-500/40',
    accentClass: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    featured: true,
  },
  {
    id: 'fnb_menu',
    name: 'Food & Beverage Menu Engineer',
    shortLabel: 'F&B Menu',
    category: 'hospitality',
    description: 'Bar & kitchen profitability: recipe costing, cocktail pricing, high-margin item design, happy hour specials, and QR digital menu sync.',
    badge: 'Menu & Margin',
    skills: 'Recipe Costing • Margins • Cocktail Engineering • QR Menus',
    icon: 'wine',
    color: 'from-rose-500/20 to-pink-500/20 text-rose-400 border-rose-500/40',
    accentClass: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
    featured: true,
  },
  {
    id: 'concierge',
    name: 'Reservations & Guest Concierge',
    shortLabel: 'Concierge',
    category: 'hospitality',
    description: 'Table & karaoke room reservations, guest flow coordination, deposit tracking, VIP preferences, and event scheduling.',
    badge: 'VIP & Bookings',
    skills: 'Room Bookings • Guest Notes • Karaoke Schedules • Deposits',
    icon: 'calendar',
    color: 'from-sky-500/20 to-blue-500/20 text-sky-400 border-sky-500/40',
    accentClass: 'text-sky-400 bg-sky-500/10 border-sky-500/30',
    featured: true,
  },
  {
    id: 'inventory',
    name: 'Inventory & Supplier Purchasing',
    shortLabel: 'Inventory',
    category: 'finance',
    description: 'Par levels, beverage/ingredient stock counts, supplier price tracking, waste reduction audits, and automated purchase orders.',
    badge: 'Stock & Orders',
    skills: 'Par Levels • Stock Audits • Supplier Orders • Spoilage Reduction',
    icon: 'boxes',
    color: 'from-amber-500/20 to-yellow-500/20 text-yellow-400 border-yellow-500/40',
    accentClass: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    featured: false,
  },
  {
    id: 'shifts',
    name: 'Staff Roster & Shift Operations',
    shortLabel: 'Staff & Shifts',
    category: 'operations',
    description: 'Weekly employee scheduling, shift handovers, tip pooling rules, labor cost vs revenue %, and staff communication.',
    badge: 'Roster & Team',
    skills: 'Shift Rosters • Labor % • Tip Pooling • Handover Logs',
    icon: 'users',
    color: 'from-teal-500/20 to-cyan-500/20 text-teal-400 border-teal-500/40',
    accentClass: 'text-teal-400 bg-teal-500/10 border-teal-500/30',
    featured: false,
  },
  {
    id: 'marketing',
    name: 'Local Marketing & Social Media',
    shortLabel: 'Marketing',
    category: 'growth',
    description: 'Instagram stories, reels copy, weekend party flyers, local Google Business SEO, promotional calendars, and neighborhood buzz.',
    badge: 'Local Reach',
    skills: 'Instagram Captions • Event Flyers • Local SEO • Promos',
    icon: 'megaphone',
    color: 'from-orange-500/20 to-amber-500/20 text-orange-400 border-orange-500/40',
    accentClass: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
    featured: true,
  },
  {
    id: 'outreach',
    name: 'B2B Outreach & Private Events',
    shortLabel: 'Outreach',
    category: 'growth',
    description: 'Venue buyout proposals, corporate karaoke team building, B2B lead enrichment, Excel CRM syncing, and Polish cold email outreach.',
    badge: 'PlaatoOS Growth',
    skills: 'plaatoos-outreach • Instagram Cowork • Excel CRM • Email Cold',
    icon: 'target',
    color: 'from-rose-500/20 to-orange-500/20 text-rose-400 border-rose-500/40',
    accentClass: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
    featured: true,
  },
  {
    id: 'reviews',
    name: 'Customer Reviews & Reputation',
    shortLabel: 'Reviews',
    category: 'growth',
    description: 'Google Maps and TripAdvisor review sentiment analysis, empathetic response drafting, negative review resolution, and review generation.',
    badge: '5-Star Polish',
    skills: 'Google Maps • Sentiment • Response Drafting • Reputation',
    icon: 'star',
    color: 'from-yellow-500/20 to-amber-500/20 text-yellow-300 border-yellow-500/40',
    accentClass: 'text-yellow-300 bg-yellow-500/10 border-yellow-500/30',
    featured: false,
  },
  {
    id: 'retention',
    name: 'VIP Loyalty & Customer Retention',
    shortLabel: 'VIP Loyalty',
    category: 'growth',
    description: 'Regular customer tracking, birthday campaigns, VIP perks, automated WhatsApp/SMS re-engagement, and repeat visit frequency.',
    badge: 'Regulars & VIP',
    skills: 'VIP Clubs • Birthday Perks • Win-Back SMS • Retention',
    icon: 'heart',
    color: 'from-pink-500/20 to-rose-500/20 text-pink-400 border-pink-500/40',
    accentClass: 'text-pink-400 bg-pink-500/10 border-pink-500/30',
    featured: false,
  },
  {
    id: 'compliance',
    name: 'Compliance, Licensing & Safety',
    shortLabel: 'Compliance',
    category: 'operations',
    description: 'Alcohol license renewal tracking, food hygiene HACCP logs, occupancy limits, local municipal regulations, and fire safety audits.',
    badge: 'Permits & Safety',
    skills: 'Alcohol Permits • HACCP Checklists • Safety Audits • Legal',
    icon: 'shield',
    color: 'from-red-500/20 to-rose-500/20 text-red-400 border-red-500/40',
    accentClass: 'text-red-400 bg-red-500/10 border-red-500/30',
    featured: false,
  },
  {
    id: 'coding',
    name: 'Coding & POS Systems',
    shortLabel: 'Coding',
    category: 'tech',
    description: 'Staff Engineer mode: filesystem tools, git operations, diagnostics, debugging, and precise code diffs.',
    badge: 'Files & Terminal',
    skills: 'Filesystem • Git • Diagnostics • Refactoring',
    icon: 'code',
    color: 'from-blue-500/20 to-indigo-500/20 text-blue-400 border-blue-500/40',
    accentClass: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
    featured: true,
  },
  {
    id: 'design',
    name: 'Design & Creative Studio',
    shortLabel: 'Design',
    category: 'tech',
    description: 'Principal Designer mode: modern Tailwind styling, UI/UX components, responsive aesthetics, and canvas previews.',
    badge: 'Tailwind & Canvas',
    skills: 'Tailwind CSS • UI/UX Components • Artifact Canvas • Aesthetics',
    icon: 'palette',
    color: 'from-purple-500/20 to-pink-500/20 text-purple-400 border-purple-500/40',
    accentClass: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
    featured: false,
  },
  {
    id: 'antigravity',
    name: 'Desktop Cowork & Automation',
    shortLabel: 'Cowork',
    category: 'tech',
    description: 'Autonomous desktop companion for open window inspection, UIA clicks, and multi-window desktop coordination.',
    badge: 'Desktop UIA',
    skills: 'Desktop Windows • UIA Clicks • Window Management',
    icon: 'bot',
    color: 'from-cyan-500/20 to-sky-500/20 text-cyan-400 border-cyan-500/40',
    accentClass: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30',
    featured: false,
  },
];

export const MODES = [
  { value: 'auto', label: 'Auto (General)' },
  { value: 'financial', label: 'Financial & Business Ops' },
  { value: 'fnb_menu', label: 'Food & Beverage Menu Engineer' },
  { value: 'concierge', label: 'Reservations & Guest Concierge' },
  { value: 'inventory', label: 'Inventory & Supplier Purchasing' },
  { value: 'shifts', label: 'Staff Roster & Shift Operations' },
  { value: 'marketing', label: 'Local Marketing & Social Media' },
  { value: 'outreach', label: 'B2B Outreach & Private Events' },
  { value: 'reviews', label: 'Customer Reviews & Reputation' },
  { value: 'retention', label: 'VIP Loyalty & Customer Retention' },
  { value: 'compliance', label: 'Compliance, Licensing & Safety' },
  { value: 'coding', label: 'Coding & POS Systems' },
  { value: 'design', label: 'Design & Creative Studio' },
  { value: 'antigravity', label: 'Desktop Cowork & Automation' },
  { value: 'direct', label: 'Local model' },
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'codex', label: 'Codex' },
  { value: 'opencode', label: 'OpenCode' },
] as const;

export type Mode = (typeof MODES)[number]['value'] | string;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${ENGINE_HTTP_URL}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status}`);
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const chatsApi = {
  list: () => request<ChatSummary[]>('/api/chats'),
  get: (id: string) => request<ChatDetail>(`/api/chats/${id}`),
  create: (title?: string, projectId?: string) =>
    request<ChatSummary>('/api/chats', {
      method: 'POST',
      body: JSON.stringify({ title, project_id: projectId }),
    }),
  remove: (id: string) => request<void>(`/api/chats/${id}`, { method: 'DELETE' }),
  removeAll: () => request<{ deleted: number }>('/api/chats', { method: 'DELETE' }),
  getContext: (id: string, modelId?: string) =>
    request<ContextMetrics>(`/api/chats/${id}/context${modelId ? `?model_id=${encodeURIComponent(modelId)}` : ''}`),
  compact: (id: string) =>
    request<CompactResult>(`/api/chats/${id}/compact`, { method: 'POST' }),
  clear: (id: string) =>
    request<{ status: string; chat_id: string }>(`/api/chats/${id}/clear`, { method: 'POST' }),
};

/** A provider or harness from GET /api/models. */
export interface ModelProvider {
  name: string;
  displayName: string;
  executionType: string;
  status: string;
  selectedModel?: string | null;
  availableModels: string[];
}

/** A model the dock can pin a chat to; empty provider means "let the mode decide". */
export interface ModelChoice {
  provider: string;
  model: string;
}

/** How a local model runs on this machine: in GPU memory (fast), split with RAM (slow), or not at all. */
export type ModelFit = 'fits_gpu' | 'slow' | 'too_big';

export interface LocalModel {
  name: string;
  sizeBytes: number;
  tools: boolean | null;
  fit: ModelFit;
  recommended: boolean;
  loaded: boolean;
  vramBytes: number;
}

export interface ModelSuggestion {
  name: string;
  sizeGb: number;
  fit: ModelFit;
  note: string;
  pull: string;
}

export interface ModelRecommendations {
  hardware: {
    gpuName: string | null;
    vramBytes: number;
    ramBytes: number;
    vramUsedBytes?: number;
    vramFreeBytes?: number;
  };
  models: LocalModel[];
  suggestions: ModelSuggestion[];
}

export const FIT_LABELS: Record<ModelFit, { icon: string; text: string }> = {
  fits_gpu: { icon: '✅', text: 'Fits your GPU: fast' },
  slow: { icon: '⚠️', text: 'Spills into RAM: slow' },
  too_big: { icon: '❌', text: 'Too big for this machine' },
};

export interface DownloadStatus {
  status: 'idle' | 'starting' | 'downloading' | 'finalizing' | 'completed' | 'error';
  step?: string;
  progress: number;
  completed?: number;
  total?: number;
  error?: string | null;
}

export const modelsApi = {
  list: () => request<{ models: ModelProvider[] }>('/api/models'),
  recommendations: () => request<ModelRecommendations>('/api/models/recommendations'),
  load: (model: string, keepAlive?: number | string) =>
    request<{ status: string; keep_alive?: number | string }>('/api/models/load', {
      method: 'POST',
      body: JSON.stringify({ model, keep_alive: keepAlive }),
    }),
  unload: (model: string) =>
    request<{ status: string }>('/api/models/unload', { method: 'POST', body: JSON.stringify({ model }) }),
  unloadAll: () =>
    request<{ status: string; unloaded: string[] }>('/api/models/unload-all', { method: 'POST' }),
  pull: (model: string) =>
    request<{ status: string; model: string }>('/api/models/pull', {
      method: 'POST',
      body: JSON.stringify({ model }),
    }),
  pullStatus: (model?: string) =>
    request<{ downloads: Record<string, DownloadStatus> }>(
      model ? `/api/models/pull/status?model=${encodeURIComponent(model)}` : '/api/models/pull/status',
    ),
  delete: (model: string) =>
    request<{ status: string; model: string }>('/api/models/delete', {
      method: 'DELETE',
      body: JSON.stringify({ model }),
    }),
};

export interface ServiceVenue {
  business_id: string;
  name: string;
  slug: string;
  icon?: string;
  active: boolean;
}

/** An MCP service Emiliano can sign in to (GET /api/mcp/connections). */
export interface ServiceConnection {
  service: string;
  title: string;
  connected: boolean;
  auth: 'oauth' | 'token' | null;
  tenant?: string;
  business_id?: string;
  venues?: ServiceVenue[];
}

export interface ConnectResult {
  ok: boolean;
  tools: number;
  hidden: number;
  error: string;
}

export const connectionsApi = {
  list: () => request<{ connections: ServiceConnection[] }>('/api/mcp/connections'),
  // Opens the browser sign-in on this computer and resolves once the user approves (or it fails)
  connect: (service: string) =>
    request<ConnectResult>('/api/mcp/connect', { method: 'POST', body: JSON.stringify({ service }) }),
  disconnect: (service: string) =>
    request<{ service: string }>('/api/mcp/disconnect', { method: 'POST', body: JSON.stringify({ service }) }),
  switchVenue: (service: string, business_id: string) =>
    request<{ ok: boolean; active_venue: string; business_id: string; venues: ServiceVenue[] }>(
      '/api/mcp/switch-venue',
      { method: 'POST', body: JSON.stringify({ service, business_id }) }
    ),
};

export interface StagedProposal {
  action_id: string;
  routine_id?: string;
  routine_name?: string;
  step_index?: number;
  tool?: string;
  arguments?: Record<string, any>;
  preview?: string;
  status: 'pending' | 'approved' | 'rejected' | 'executed';
  created_at?: string;
}

export const stagedApi = {
  list: (status: string = 'pending') =>
    request<{ staged_actions: StagedProposal[] }>(`/api/routines/staged?status=${status}`),
  approve: (action_id: string) =>
    request<{ status: string }>(`/api/routines/staged/${action_id}/approve`, { method: 'POST' }),
  reject: (action_id: string) =>
    request<{ status: string }>(`/api/routines/staged/${action_id}/reject`, { method: 'POST' }),
};

export interface SkillItem {
  id: string;
  title: string;
  description: string;
  intents?: string[];
  triggers?: string[];
  category: 'workflow' | 'system' | 'custom';
  enabled?: boolean;
  status?: 'active' | 'staged' | 'archived';
  version?: string;
  badge?: string;
  path?: string;
  quickActions?: string[];
  selectors?: Record<string, string>;
  instructions_md?: string;
}

export interface ProjectItem {
  id: string;
  name: string;
  description: string;
  root_path: string;
  system_prompt: string;
  created_at: string;
  updated_at: string;
  chat_count: number;
}

export interface ArtifactItem {
  id: string;
  chat_id?: string;
  project_id?: string;
  title: string;
  kind: 'html' | 'code' | 'diagram' | 'plan' | 'diff' | 'markdown';
  content: string;
  file_path?: string;
  created_at: string;
  updated_at: string;
}

export const skillsApi = {
  list: () => request<{ skills: SkillItem[] }>('/api/skills'),
};

export interface RoutineItem {
  id: string;
  name: string;
  description: string;
  bot_persona: string;
  skill_id?: string;
  goal_template?: string;
  inputs?: Record<string, any>;
  trigger: {
    type: 'cron' | 'interval' | 'webhook' | 'manual';
    cron_expression?: string;
    interval_seconds?: number;
    webhook_path?: string;
  };
  enabled: boolean;
  last_run_at?: number;
  next_run_at?: number;
  total_runs: number;
}

export interface StagedActionItem {
  id: string;
  routine_id: string;
  run_id: string;
  action_type: string;
  target: string;
  payload: Record<string, any>;
  status: 'pending' | 'approved' | 'rejected' | 'executed';
  created_at: number;
  notes?: string;
}

export const routinesApi = {
  list: (enabledOnly = false) =>
    request<{ routines: RoutineItem[] }>(`/api/routines${enabledOnly ? '?enabled_only=true' : ''}`),
  create: (body: Partial<RoutineItem>) =>
    request<RoutineItem>('/api/routines', { method: 'POST', body: JSON.stringify(body) }),
  trigger: (id: string, inputs?: Record<string, any>) =>
    request<any>(`/api/routines/${id}/trigger`, { method: 'POST', body: JSON.stringify({ inputs }) }),
  listStaged: (status = 'pending') =>
    request<{ staged_actions: StagedActionItem[] }>(`/api/routines/staged?status=${status}`),
  approveStaged: (id: string) =>
    request<StagedActionItem>(`/api/routines/staged/${id}/approve`, { method: 'POST' }),
  rejectStaged: (id: string, notes?: string) =>
    request<StagedActionItem>(`/api/routines/staged/${id}/reject`, { method: 'POST', body: JSON.stringify({ notes }) }),
};

export const projectsApi = {
  list: () => request<ProjectItem[]>('/api/projects'),
  get: (id: string) => request<ProjectItem & { chats: ChatSummary[] }>(`/api/projects/${id}`),
  create: (body: { name: string; root_path?: string; description?: string; system_prompt?: string }) =>
    request<ProjectItem>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: string, body: { name?: string; root_path?: string; description?: string; system_prompt?: string }) =>
    request<ProjectItem>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  openFolder: (id: string) =>
    request<{ opened: boolean; path: string }>(`/api/projects/${id}/open-folder`, { method: 'POST' }),
  remove: (id: string) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),
};

export const artifactsApi = {
  list: (params?: { chatId?: string; projectId?: string; kind?: string }) => {
    const q = new URLSearchParams();
    if (params?.chatId) q.set('chat_id', params.chatId);
    if (params?.projectId) q.set('project_id', params.projectId);
    if (params?.kind) q.set('kind', params.kind);
    const qs = q.toString();
    return request<ArtifactItem[]>(`/api/artifacts${qs ? `?${qs}` : ''}`);
  },
  get: (id: string) => request<ArtifactItem>(`/api/artifacts/${id}`),
  create: (body: { title: string; kind?: string; content: string; chat_id?: string; project_id?: string; file_path?: string }) =>
    request<ArtifactItem>('/api/artifacts', { method: 'POST', body: JSON.stringify(body) }),
  openFile: (id: string) =>
    request<{ opened: boolean; path: string }>(`/api/artifacts/${id}/open`, { method: 'POST' }),
  remove: (id: string) => request<void>(`/api/artifacts/${id}`, { method: 'DELETE' }),
};

export function formatGb(bytes: number): string {
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

/** Ready direct models (local Ollama and API providers with keys); harnesses pick their own model. */
export function directModelGroups(providers: ModelProvider[]): ModelProvider[] {
  return providers.filter(
    (p) => p.executionType === 'direct_model' && p.status === 'ready' && p.availableModels.length > 0,
  );
}

/** "2m", "3h", "Yesterday", "Oct 12" — compact enough for the 420px dock. */
export function relativeTime(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)}h`;
  if (minutes < 48 * 60) return 'Yesterday';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
