import { z } from 'zod';
import request, { prepareBrowserHeaders } from './request';

const positive = z.number().int().safe().positive();
// Branded local refs cannot be populated from Native file-row tag IDs.
const ref = positive.brand<'ProviderTagRef'>();
export type ProviderTagRef = z.infer<typeof ref>;
const refs = z.array(ref).refine(values => new Set(values).size === values.length);
const snapshot = z.object({ generation: positive, revision: z.number().int().safe().nonnegative(),
  tag_ref_ids: refs, edit_contract: z.literal('manual-tags-v1') });
const catalog = z.object({ generation: positive, total: z.number().int().safe().nonnegative(),
  data: z.array(z.object({ tag_ref_id: ref, name: z.string().min(1) })) });
const envelope = z.object({ status_code: z.literal(200), data: z.unknown() });
export const MAX_MANUAL_TAGS = 50;
export type ProviderTagTarget = { spaceId: string; generation: number; tenant: string };
const spacePath = (target: ProviderTagTarget) => `/api/v1/knowledge/space/${encodeURIComponent(target.spaceId)}`;
const filePath = (target: ProviderTagTarget, fileId: string) => `${spacePath(target)}/files/${encodeURIComponent(fileId)}/provider-tags`;

async function options(method: string, url: string, target: ProviderTagTarget) {
  const headers = await prepareBrowserHeaders(method, url);
  if (headers['X-Management-Tenant'] !== target.tenant) throw new Error('Tag scope changed');
  return { headers: { 'X-Management-Tenant': target.tenant }, managementContext: 'independent' as const, showError: false };
}
async function read(target: ProviderTagTarget, url: string, signal?: AbortSignal, params?: Record<string, number>) {
  const response = await request.getResponse<{ headers: Record<string, string>; data: unknown }>(url, {
    ...await options('GET', url, target), signal, params: { ...params, generation: target.generation },
  });
  if (response.headers['x-management-tenant'] !== target.tenant) throw new Error('Tag scope changed');
  return envelope.parse(response.data).data;
}
export async function readTagPage(target: ProviderTagTarget, page: number, pageSize: number, signal?: AbortSignal) {
  const value = catalog.parse(await read(target, `${spacePath(target)}/provider-tags`, signal, { page, page_size: pageSize }));
  if (value.generation !== target.generation || value.data.length > pageSize || new Set(value.data.map(t => t.tag_ref_id)).size !== value.data.length) throw new Error('Invalid tag page');
  return value;
}
export async function readManualTags(target: ProviderTagTarget, fileId: string, signal?: AbortSignal) {
  const value = snapshot.parse(await read(target, filePath(target, fileId), signal));
  if (value.generation !== target.generation) throw new Error('Tag generation changed');
  return value;
}
export async function saveManualTags(target: ProviderTagTarget, fileId: string, revision: number, mode: 'replace' | 'clear', tagRefs: ProviderTagRef[]) {
  if (tagRefs.length > MAX_MANUAL_TAGS || (mode === 'clear') !== (tagRefs.length === 0)) throw new Error('Invalid manual tag selection');
  const url = filePath(target, fileId);
  const data = await request.put(url, { generation: target.generation, mode, expected_revision: revision, tag_ref_ids: tagRefs }, await options('PUT', url, target));
  const value = snapshot.parse(envelope.parse(data).data);
  const confirmed = new Set(value.tag_ref_ids);
  if (value.generation !== target.generation || confirmed.size !== tagRefs.length || tagRefs.some(id => !confirmed.has(id))) throw new Error('Unconfirmed tag write');
}
