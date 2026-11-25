import request, { prepareBrowserHeaders } from './request';

const root = '/api/v1/knowledge/space';
export type SpaceProvider = 'native' | 'weknora';
export type ProviderConfig = {
  type: 'document'; model_policy: 'bisheng-v1'; preset_revision: number;
  summary_model_id: string; summary_version: string;
  embedding_model_id: string; embedding_version: string; embedding_dimension: number;
  vision_model_id: string; vision_version: string;
  wiki_model_id: string | null; tag_model_id: string | null;
  chunk_size: number; overlap: number;
  vector_index_enabled: boolean; keyword_index_enabled: boolean; wiki_enabled: boolean;
  entities_enabled: boolean; multimodal_enabled: boolean; auto_tag_enabled: boolean;
};
const flags = ['vector_index_enabled', 'keyword_index_enabled', 'wiki_enabled', 'entities_enabled', 'multimodal_enabled', 'auto_tag_enabled'] as const;
const text = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const integer = (value: unknown, min: number): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min;
function isConfig(value: unknown, creation: boolean): value is ProviderConfig {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return v.type === 'document' && v.model_policy === 'bisheng-v1' && integer(v.preset_revision, 1)
    && [v.summary_model_id, v.summary_version, v.embedding_model_id, v.embedding_version, v.vision_model_id, v.vision_version].every(text)
    && new Set([v.summary_model_id, v.embedding_model_id, v.vision_model_id]).size === 3
    && integer(v.embedding_dimension, 1) && integer(v.chunk_size, 1) && integer(v.overlap, 0) && v.overlap < v.chunk_size
    && [v.wiki_model_id, v.tag_model_id].every(id => id === null || (!creation && text(id)))
    && flags.every(key => typeof v[key] === 'boolean' && (!creation || v[key] === true));
}
export type ReviewedPreset = { tenant: string; config: ProviderConfig };
export async function previewProviderPreset(): Promise<ReviewedPreset> {
  const response = await request.getResponse<{ headers: Record<string, string>; data: { data: unknown } }>(`${root}/creation-settings`, { params: { provider_key: 'weknora' } });
  const tenant = response.headers['x-management-tenant'];
  const config = response.data.data;
  if (!/^[1-9]\d*$/.test(tenant) || !Number.isSafeInteger(Number(tenant)) || !isConfig(config, true)) throw new Error('Unverified preset');
  return { tenant, config };
}
export async function createProviderSpace(preset: ReviewedPreset, requestId: string, fields: { name: string; description: string; auth_type: string; is_released: boolean }) {
  const current = await prepareBrowserHeaders('POST', root);
  if (current['X-Management-Tenant'] !== preset.tenant) throw Object.assign(new Error('management_scope_changed'), { status_code: 19704 });
  const { data } = await request.post(root, {
    ...fields, provider_key: 'weknora', creation_request_id: requestId, preset_summary: preset.config,
  }, { headers: { 'X-Management-Tenant': preset.tenant } });
  if (!text(data?.operation_id) || !integer(data.space_id, 1) || !text(data.state)) throw new Error('Invalid operation receipt');
  return { operationId: data.operation_id, state: data.state };
}
export async function getSpaceProvider(spaceId: string): Promise<SpaceProvider> {
  const { data } = await request.get<{ data: { provider_key: string } }>(`${root}/${encodeURIComponent(spaceId)}/capabilities`);
  if (data.provider_key !== 'native' && data.provider_key !== 'weknora') throw new Error('Unknown space provider');
  return data.provider_key;
}
export async function readProviderSettings(spaceId: string) {
  const { data } = await request.get<{ data: { revision: number; settings: unknown; pending: string | null } }>(`${root}/${encodeURIComponent(spaceId)}/settings`);
  if (!integer(data.revision, 1) || !isConfig(data.settings, false) || !(data.pending === null || text(data.pending))) throw new Error('Unverified settings');
  return { config: data.settings, revision: data.revision, pending: Boolean(data.pending) };
}
