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

export interface ResponseMetrics {
  total_duration_s: number;
  formatted_duration: string;
  ttft_ms?: number;
  tokens_per_second?: number;
  completion_tokens?: number;
  prompt_tokens?: number;
  tool_duration_s?: number;
  tools_count?: number;
  route?: string;
  status?: string;
  tool_calls?: ToolCallRecord[];
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

/** The dock's mode dropdown; values match the engine's resolve_mode(). */
export const MODES = [
  { value: 'auto', label: 'Auto' },
  { value: 'direct', label: 'Local model' },
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'codex', label: 'Codex' },
  { value: 'antigravity', label: 'Antigravity' },
  { value: 'opencode', label: 'OpenCode' },
] as const;

export type Mode = (typeof MODES)[number]['value'];

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

/** An MCP service Emiliano can sign in to (GET /api/mcp/connections). */
export interface ServiceConnection {
  service: string;
  title: string;
  connected: boolean;
  auth: 'oauth' | 'token' | null;
  tenant?: string;
  business_id?: string;
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
