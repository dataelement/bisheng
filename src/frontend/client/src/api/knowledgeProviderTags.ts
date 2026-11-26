import { z } from 'zod';
import request, { prepareBrowserHeaders } from './request';

const positive = z.number().int().safe().positive();
// Branded local refs cannot be populated from Native file-row tag IDs.
const ref = positive.brand<'ProviderTagRef'>();
export type ProviderTagRef = z.infer<typeof ref>;
const refs = z.array(ref).refine(values => new Set(values).size === values.length);
/** `whole-tags-v1` is the degraded upstream shape: one tag list per document, no revision guard. */
const CONTRACTS = ['manual-tags-v1', 'whole-tags-v1'] as const;
export type ProviderTagContract = typeof CONTRACTS[number];
const snapshot = z.object({ generation: positive, revision: z.number().int().safe().nonnegative(),
  tag_ref_ids: refs, edit_contract: z.enum(CONTRACTS) });
const catalog = z.object({ generation: positive, total: z.number().int().safe().nonnegative(),
  data: z.array(z.object({ tag_ref_id: ref, name: z.string().min(1) })) });
const created = z.object({ tag_ref_id: ref, name: z.string().min(1), generation: positive });
const envelope = z.object({ status_code: z.literal(200), data: z.unknown() });
export const MAX_MANUAL_TAGS = 50;
export const MAX_TAG_NAME_LENGTH = 128;
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
const labels = z.object({ generation: positive, names: z.array(z.string().min(1)) });
/** Display-only names for one document. The file list calls it per opened row, never per page. */
export async function readProviderTagLabels(target: ProviderTagTarget, fileId: string, signal?: AbortSignal) {
  const url = `${spacePath(target)}/files/${encodeURIComponent(fileId)}/provider-tag-labels`;
  const value = labels.parse(await read(target, url, signal));
  if (value.generation !== target.generation) throw new Error('Tag generation changed');
  return value.names;
}
/** Creates one space word (needs space tag management rights); it is not attached to any file yet. */export async function createProviderTag(target: ProviderTagTarget, name: string) {
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > MAX_TAG_NAME_LENGTH) throw new Error('Invalid tag name');
  const url = `${spacePath(target)}/provider-tags`;
  const data = await request.post(url, { generation: target.generation, name: trimmed }, await options('POST', url, target));
  const value = created.parse(envelope.parse(data).data);
  if (value.generation !== target.generation || value.name !== trimmed) throw new Error('Unconfirmed tag creation');
  return value;
}
