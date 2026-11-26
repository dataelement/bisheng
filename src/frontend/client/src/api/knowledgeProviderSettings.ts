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
export type ExtractConfig = {
  text: string;
  tags: string[];
  nodes: { name: string }[];
  relations: { node1: string; type: string; node2: string }[];
};
export type ProviderSelection = {
  summary_model_id: string; embedding_model_id: string; vision_model_id: string; chunk_size: number; overlap: number;
} & (
  | { extract_template_kb_id: string; extract_config?: never }
  | { extract_config: ExtractConfig; extract_template_kb_id?: never }
);
export type ProviderModel = { id: string; name: string; display_name: string; dimension?: number };
export type ProviderModels = Record<'chat' | 'embedding' | 'vision', ProviderModel[]>;
export type ExtractTemplate = { id: string; name: string };
export const CHUNK_SIZE_MAX = 100000;
const PREVIEW_KEYS = ['summary_model_id', 'embedding_model_id', 'vision_model_id', 'chunk_size', 'overlap'] as const;

function isExtract(value: unknown): value is ExtractConfig {
  if (!value || typeof value !== 'object') return false;
  const v = value as ExtractConfig;
  if (!text(v.text) || !Array.isArray(v.tags) || v.tags.length === 0 || !v.tags.every(text)) return false;
  if (!Array.isArray(v.nodes) || v.nodes.length === 0 || !v.nodes.every(n => text(n?.name))) return false;
  const names = v.nodes.map(n => n.name);
  if (new Set(names).size !== names.length) return false;
  const known = new Set(names);
  return Array.isArray(v.relations) && v.relations.length > 0
    && v.relations.every(r => known.has(r?.node1) && known.has(r?.node2) && text(r?.type));
}

export function isCompleteSelection(s: {
  summary_model_id?: string | null; embedding_model_id?: string | null; vision_model_id?: string | null;
  chunk_size?: number | null; overlap?: number | null;
  extract_template_kb_id?: string | null; extract_config?: ExtractConfig | null;
}): s is ProviderSelection {
  const base = [s.summary_model_id, s.embedding_model_id, s.vision_model_id].every(text)
    && new Set([s.summary_model_id, s.embedding_model_id, s.vision_model_id]).size === 3
    && integer(s.chunk_size, 1) && s.chunk_size! <= CHUNK_SIZE_MAX && integer(s.overlap, 0) && s.overlap! < s.chunk_size!;
  if (!base) return false;
  const hasTemplate = text(s.extract_template_kb_id);
  const hasConfig = s.extract_config != null && isExtract(s.extract_config);
  return hasTemplate !== hasConfig && (hasTemplate || hasConfig);
}

function isModel(value: unknown, embedding: boolean): value is ProviderModel {
  const m = value as Record<string, unknown> | null;
  return !!m && [m.id, m.name, m.display_name].every(text) && (!embedding || integer(m.dimension, 1));
}

export async function listProviderModels(): Promise<ProviderModels> {
  const { data } = await request.get<{ data: Record<string, unknown> }>(`${root}/provider-models`);
  const kinds = ['chat', 'embedding', 'vision'] as const;
  if (!kinds.every(kind => Array.isArray(data?.[kind]) && (data[kind] as unknown[]).every(m => isModel(m, kind === 'embedding')))) {
    throw new Error('Invalid model list');
  }
  return data as ProviderModels;
}

export async function listExtractTemplates(): Promise<ExtractTemplate[]> {
  const { data } = await request.get<{ data: unknown }>(`${root}/provider-extract-templates`);
  const template = (row: unknown): boolean => {
    const r = row as Record<string, unknown> | null;
    return !!r && text(r.id) && text(r.name);
  };
  if (!Array.isArray(data) || !data.every(template)) throw new Error('Invalid extract templates');
  return data as ExtractTemplate[];
}

export type ReviewedPreset = { tenant: string; config: ProviderConfig; selection: ProviderSelection };
export async function previewProviderPreset(selection: ProviderSelection, signal?: AbortSignal): Promise<ReviewedPreset> {
  // Must use postResponse: getResponse is axios.get and cannot carry the selection body.
  // Pass a config object so the body stays a plain object (not JSON.stringify).
  // A superseded preview is aborted: its model probes are full remote inferences,
  // so leaving one running only makes the next request queue behind it.
  const response = await request.postResponse<{ headers: { get?(name: string): string; [key: string]: unknown }; data: { data: unknown } }>(
    `${root}/creation-settings`,
    { provider_key: 'weknora', provider_selection: selection },
    signal ? { signal } : {},
  );
  const headers = response.headers;
  const tenant = String(headers?.get?.('x-management-tenant') ?? headers?.['x-management-tenant'] ?? '');
  const config = response.data.data;
  if (!/^[1-9]\d*$/.test(tenant) || !Number.isSafeInteger(Number(tenant)) || !isConfig(config, true)) throw new Error('Unverified preset');
  if (PREVIEW_KEYS.some(key => (config as ProviderConfig)[key] !== selection[key])) throw new Error('Unverified preset');
  return { tenant, config, selection };
}
export async function createProviderSpace(preset: ReviewedPreset, requestId: string, fields: { name: string; description: string; auth_type: string; is_released: boolean }) {
  const current = await prepareBrowserHeaders('POST', root);
  if (current['X-Management-Tenant'] !== preset.tenant) throw Object.assign(new Error('management_scope_changed'), { status_code: 19704 });
  const { data } = await request.post(root, {
    ...fields, provider_key: 'weknora', creation_request_id: requestId, preset_summary: preset.config, provider_selection: preset.selection,
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
