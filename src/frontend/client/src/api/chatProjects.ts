import request from './request';
import type { TConversation } from '~/types/chat';
import { tConversationSchema } from '~/types/chat';

export type CloudProject = { id: string; name: string; created_at?: string; updated_at?: string };
export type ProjectSnapshot = {
  protocol_version: 1;
  identity: { user_id: number; tenant_id: number };
  revision: string;
  projects: CloudProject[];
  memberships: Array<{ chat_id: string; project_id: string }>;
  next_cursor: string | null;
};
export type ProjectOperation =
  | { operation: 'create'; name: string; chat_id?: string }
  | { operation: 'rename'; project_id: string; name: string }
  | { operation: 'delete'; project_id: string }
  | { operation: 'assign'; chat_id: string; project_id: string | null }
  | { operation: 'import'; source_client_id: string; projects: Array<{ legacy_id: string; name: string; created_at?: string }>; memberships: Array<{ chat_id: string; legacy_project_id: string }> };
export type ProjectActionResult = { revision: string; applied_revision: string; replayed: boolean; notification: 'live' | 'degraded'; outcome: { project_id?: string; chat_id?: string; items?: Array<{ kind: string; status: string; legacy_id?: string; chat_id?: string }> } };
export type ProjectConversationPage = { data: TConversation[]; total: number; revision: string; next_cursor: string | null };
export type ProjectEvent = { protocol_version: 1; revision: string; notification?: 'live' | 'degraded'; reason?: string };

export class ProjectApiError extends Error {
  constructor(public readonly code = 13016) { super(`Project operation failed (${code})`); }
}

export function newProjectRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 15) | 64;
  bytes[8] = ((bytes[8] ?? 0) & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function validProjectRevision(value: unknown): value is string {
  return typeof value === 'string' && /^(0|[1-9]\d{0,19})$/.test(value);
}
const validUuid = (value: unknown): value is string => typeof value === 'string' && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value);
const validChatId = (value: unknown): value is string => typeof value === 'string' && /^[a-z\d_-]{1,255}$/i.test(value);
export function unwrapProjectEnvelope(value: unknown): unknown {
  if (!record(value) || value.status_code !== 200) throw new ProjectApiError(record(value) && typeof value.status_code === 'number' ? value.status_code : 13016);
  return value.data;
}
function snapshotPage(value: unknown): ProjectSnapshot {
  if (!record(value) || value.protocol_version !== 1 || !validProjectRevision(value.revision) || !record(value.identity) ||
      !Number.isSafeInteger(value.identity.user_id) || Number(value.identity.user_id) < 1 || !Number.isSafeInteger(value.identity.tenant_id) || Number(value.identity.tenant_id) < 1 ||
      !Array.isArray(value.projects) || value.projects.length > 500 || !Array.isArray(value.memberships) || value.memberships.length > 500 ||
      !(value.next_cursor === null || (typeof value.next_cursor === 'string' && value.next_cursor.length <= 2048))) throw new ProjectApiError();
  if (value.projects.some(p => !record(p) || !validUuid(p.id) || typeof p.name !== 'string' || !p.name.trim() || p.name.length > 30) ||
      value.memberships.some(m => !record(m) || !validChatId(m.chat_id) || !validUuid(m.project_id))) throw new ProjectApiError();
  // Every nested shape above was checked at the untrusted API boundary.
  return value as ProjectSnapshot;
}

const endpoint = 'api/v1/chat/projects';
const options = (signal?: AbortSignal) => ({ signal, timeout: 15000, showError: false, skipMaintenance: true });

export async function fetchProjectSnapshot(signal: AbortSignal, observedVersion = () => '0'): Promise<ProjectSnapshot> {
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      let snapshot: ProjectSnapshot | undefined;
      let cursor: string | null = null;
      const seen = new Set<string>();
      do {
        if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
        const page = snapshotPage(unwrapProjectEnvelope(await request.get<unknown>(`${endpoint}/snapshot`, { ...options(signal), params: cursor ? { cursor } : undefined })));
        if (snapshot && (page.revision !== snapshot.revision || page.identity.user_id !== snapshot.identity.user_id || page.identity.tenant_id !== snapshot.identity.tenant_id)) throw new ProjectApiError(13013);
        snapshot = snapshot ? { ...page, projects: [...snapshot.projects, ...page.projects], memberships: [...snapshot.memberships, ...page.memberships] } : page;
        cursor = page.next_cursor;
        if (cursor && seen.has(cursor)) throw new ProjectApiError();
        if (cursor) seen.add(cursor);
        if (snapshot.projects.length + snapshot.memberships.length > 1000000) throw new ProjectApiError();
      } while (cursor);
      if (!snapshot || BigInt(snapshot.revision) < BigInt(observedVersion())) throw new ProjectApiError(13013);
      // Validate references only after every page is assembled: a membership
      // page may legitimately refer to a project from an earlier page.
      const projectIds = new Set(snapshot.projects.map(project => project.id));
      const chatIds = new Set(snapshot.memberships.map(member => member.chat_id));
      if (projectIds.size !== snapshot.projects.length || chatIds.size !== snapshot.memberships.length || snapshot.memberships.some(member => !projectIds.has(member.project_id))) throw new ProjectApiError();
      return snapshot;
    } catch (error) {
      if (!(error instanceof ProjectApiError) || error.code !== 13013 || attempt === 5) throw error;
    }
  }
  throw new ProjectApiError();
}

export async function performProjectAction(operation: ProjectOperation, requestId: string, signal?: AbortSignal): Promise<ProjectActionResult> {
  const data = unwrapProjectEnvelope(await request.post(`${endpoint}/actions`, { ...operation, request_id: requestId }, options(signal)));
  if (!record(data) || !validProjectRevision(data.revision) || !validProjectRevision(data.applied_revision) || !record(data.outcome) || typeof data.replayed !== 'boolean' || !['live', 'degraded'].includes(String(data.notification))) throw new ProjectApiError();
  if (data.outcome.items !== undefined && (!Array.isArray(data.outcome.items) || data.outcome.items.length > 600 || data.outcome.items.some(item => !record(item) || typeof item.kind !== 'string' || typeof item.status !== 'string' || item.status.length > 64 || (item.chat_id !== undefined && typeof item.chat_id !== 'string') || (item.legacy_id !== undefined && typeof item.legacy_id !== 'string')))) throw new ProjectApiError();
  return data as ProjectActionResult;
}

export async function fetchProjectConversations(input: { project_id?: string; query?: string; cursor?: string }, signal?: AbortSignal): Promise<ProjectConversationPage> {
  const data = unwrapProjectEnvelope(await request.get<unknown>(`${endpoint}/conversations`, { ...options(signal), params: input }));
  if (!record(data) || !Array.isArray(data.data) || data.data.length > 100 || !validProjectRevision(data.revision) || !Number.isSafeInteger(data.total) || Number(data.total) < 0 || !(data.next_cursor === null || (typeof data.next_cursor === 'string' && data.next_cursor.length <= 2048))) throw new ProjectApiError();
  return { data: data.data.map(row => {
    if (!record(row) || typeof row.chat_id !== 'string' || typeof row.flow_id !== 'string' || typeof row.flow_type !== 'number') throw new ProjectApiError();
    // BiSheng conversation metadata does not identify a model-provider endpoint.
    const conversation = tConversationSchema.safeParse({ ...row, updatedAt: row.update_time, endpoint: null });
    if (!conversation.success) throw new ProjectApiError();
    return { ...conversation.data, flowId: row.flow_id, flowType: row.flow_type };
  }), total: Number(data.total), revision: data.revision, next_cursor: data.next_cursor };
}

/** API-owned stream transport; no component makes ad-hoc HTTP requests. */
export async function streamProjectEvents(signal: AbortSignal, receive: (event: string, data: ProjectEvent) => void): Promise<void> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, { once: true });
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const touch = () => { clearTimeout(watchdog); watchdog = setTimeout(abort, 45000); };
  try {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    touch();
    const base = String(__APP_ENV__.BASE_URL || '/workspace').replace(/\/$/, '');
    const response = await fetch(`${base}/api/v1/chat/projects/events`, { credentials: 'include', redirect: 'error', signal: controller.signal, headers: { Accept: 'text/event-stream' } });
    if (response.status === 401 || response.status === 403) receive('auth_required', { protocol_version: 1, revision: '0' });
    if (!response.ok || !response.headers.get('content-type')?.startsWith('text/event-stream') || !response.body) throw new ProjectApiError();
    reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let buffer = '';
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) throw new ProjectApiError();
      buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replace(/\r\n/g, '\n');
      let end: number;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        if (end > 16384) throw new ProjectApiError();
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const lines = frame.split('\n');
        const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim();
        const raw = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
        if (!event || !raw) continue;
        const data: unknown = JSON.parse(raw);
        if (!record(data) || data.protocol_version !== 1 || !validProjectRevision(data.revision) || !['ready', 'changed', 'heartbeat', 'auth_required'].includes(event)) throw new ProjectApiError();
        touch();
        receive(event, data as ProjectEvent);
      }
      if (buffer.length > 16384) throw new ProjectApiError();
    }
  } finally {
    clearTimeout(watchdog);
    signal.removeEventListener('abort', abort);
    controller.abort();
    if (reader) { try { await reader.cancel(); } finally { reader.releaseLock(); } }
  }
}
