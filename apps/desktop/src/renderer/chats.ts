// Client for the engine's saved chats API (see packages/engine/emiliano/history/api.py)

export const ENGINE_HTTP_URL = 'http://127.0.0.1:8765';
export const CHAT_WS_URL = 'ws://127.0.0.1:8765/api/chat';

export interface ChatSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
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
  create: () => request<ChatSummary>('/api/chats', { method: 'POST', body: '{}' }),
  remove: (id: string) => request<void>(`/api/chats/${id}`, { method: 'DELETE' }),
  removeAll: () => request<{ deleted: number }>('/api/chats', { method: 'DELETE' }),
  getContext: (id: string, modelId?: string) =>
    request<ContextMetrics>(`/api/chats/${id}/context${modelId ? `?model_id=${encodeURIComponent(modelId)}` : ''}`),
  compact: (id: string) =>
    request<CompactResult>(`/api/chats/${id}/compact`, { method: 'POST' }),
};

/** "2m", "3h", "Yesterday", "Oct 12" — compact enough for the 420px dock. */
export function relativeTime(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)}h`;
  if (minutes < 48 * 60) return 'Yesterday';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
