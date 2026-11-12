import request from './request';
import type { TConversation } from '~/types/chat';
import { tConversationSchema } from '~/types/chat';

export type CloudProject = { id: string; name: string; created_at?: string; updated_at?: string };
export type ProjectSnapshot = {
  identity: { user_id: number; tenant_id: number };
  projects: CloudProject[];
  memberships: Array<{ chat_id: string; project_id: string }>;
};
export type ProjectOperation =
  | { operation: 'create'; project_id: string; name: string; chat_id?: string }
  | { operation: 'rename'; project_id: string; name: string }
  | { operation: 'delete'; project_id: string }
  | { operation: 'assign'; chat_id: string; project_id: string | null }
  | { operation: 'import'; projects: Array<{ legacy_id: string; name: string; created_at?: string }>; memberships: Array<{ chat_id: string; legacy_project_id: string }> };
export type ProjectImportItem = { kind: string; status: string; legacy_id?: string; chat_id?: string; project_id?: string };
export type ProjectActionResult = { outcome: { project_id?: string; chat_id?: string; items?: ProjectImportItem[] } };
export type ProjectConversationPage = { data: TConversation[]; total: number; next_cursor: string | null };

export class ProjectApiError extends Error {
  constructor(public readonly code?: number) { super(`Project operation failed (${code})`); }
}

/** Client-generated project id: retrying the same create returns the same project. */
export function newProjectId(): string {
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
const validUuid = (value: unknown): value is string => typeof value === 'string' && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(value);
const validChatId = (value: unknown): value is string => typeof value === 'string' && /^[a-z\d_-]{1,255}$/i.test(value);
export function unwrapProjectEnvelope(value: unknown): unknown {
  if (!record(value) || value.status_code !== 200) throw new ProjectApiError(record(value) && typeof value.status_code === 'number' ? value.status_code : undefined);
  return value.data;
}
function parseSnapshot(value: unknown): ProjectSnapshot {
  if (!record(value) || !record(value.identity) ||
      !Number.isSafeInteger(value.identity.user_id) || Number(value.identity.user_id) < 1 || !Number.isSafeInteger(value.identity.tenant_id) || Number(value.identity.tenant_id) < 1 ||
      !Array.isArray(value.projects) || !Array.isArray(value.memberships)) throw new ProjectApiError();
  if (value.projects.some(p => !record(p) || !validUuid(p.id) || typeof p.name !== 'string' || !p.name.trim() || p.name.length > 30) ||
      value.memberships.some(m => !record(m) || !validChatId(m.chat_id) || !validUuid(m.project_id))) throw new ProjectApiError();
  // Every nested shape above was checked at the untrusted API boundary.
  const snapshot = value as ProjectSnapshot;
  const projectIds = new Set(snapshot.projects.map(project => project.id));
  if (snapshot.memberships.some(member => !projectIds.has(member.project_id))) throw new ProjectApiError();
  return snapshot;
}

const endpoint = 'api/v1/chat/projects';
const options = (signal?: AbortSignal) => ({ signal, timeout: 15000, showError: false, skipMaintenance: true });

export async function fetchProjectSnapshot(signal?: AbortSignal): Promise<ProjectSnapshot> {
  return parseSnapshot(unwrapProjectEnvelope(await request.get<unknown>(`${endpoint}/snapshot`, options(signal))));
}

export async function performProjectAction(operation: ProjectOperation, signal?: AbortSignal): Promise<ProjectActionResult> {
  const data = unwrapProjectEnvelope(await request.post(`${endpoint}/actions`, operation, options(signal)));
  if (!record(data) || !record(data.outcome)) throw new ProjectApiError();
  if (data.outcome.items !== undefined && (!Array.isArray(data.outcome.items) || data.outcome.items.some(item => !record(item) || typeof item.kind !== 'string' || typeof item.status !== 'string' || item.status.length > 64 || (item.chat_id !== undefined && typeof item.chat_id !== 'string') || (item.legacy_id !== undefined && typeof item.legacy_id !== 'string')))) throw new ProjectApiError();
  return data as ProjectActionResult;
}

export async function fetchProjectConversations(input: { project_id?: string; query?: string; cursor?: string }, signal?: AbortSignal): Promise<ProjectConversationPage> {
  const data = unwrapProjectEnvelope(await request.get<unknown>(`${endpoint}/conversations`, { ...options(signal), params: input }));
  if (!record(data) || !Array.isArray(data.data) || data.data.length > 100 || !Number.isSafeInteger(data.total) || Number(data.total) < 0 || !(data.next_cursor === null || (typeof data.next_cursor === 'string' && /^\d{1,9}$/.test(data.next_cursor)))) throw new ProjectApiError();
  return { data: data.data.map(row => {
    if (!record(row) || typeof row.chat_id !== 'string' || typeof row.flow_id !== 'string' || typeof row.flow_type !== 'number') throw new ProjectApiError();
    // BiSheng conversation metadata does not identify a model-provider endpoint.
    const conversation = tConversationSchema.safeParse({ ...row, updatedAt: row.update_time, endpoint: null });
    if (!conversation.success) throw new ProjectApiError();
    return { ...conversation.data, flowId: row.flow_id, flowType: row.flow_type };
  }), total: Number(data.total), next_cursor: data.next_cursor };
}
