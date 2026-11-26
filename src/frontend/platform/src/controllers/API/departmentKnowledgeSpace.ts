import axios from "../request";

export interface DepartmentKnowledgeSpaceSummary {
  id: number;
  name: string;
  department_id?: number | null;
  department_name?: string | null;
  space_kind?: "normal" | "department";
  auth_type?: string;
  is_released?: boolean;
  is_hidden?: boolean;
}

export async function getDepartmentKnowledgeSpacesApi(params?: {
  order_by?: "name" | "update_time";
  include_hidden?: boolean;
}): Promise<DepartmentKnowledgeSpaceSummary[]> {
  return await axios.get(`/api/v1/knowledge/space/department/all`, { params });
}

export async function batchCreateDepartmentKnowledgeSpacesApi(
  departmentIds: number[],
): Promise<DepartmentKnowledgeSpaceSummary[]> {
  return await axios.post(`/api/v1/knowledge/space/department/batch-create`, {
    items: departmentIds.map((department_id) => ({ department_id })),
  });
}

export type DepartmentReceipt = { departmentId: number; status: 'confirmed' | 'failed' | 'unconfirmed' };
type WireItem = { department_id: number; state?: string; admission?: string; authorization?: string; operation_id?: string };
const base = '/api/v1/knowledge/space/department';
const pinned = (tenant: number) => ({ headers: { 'X-Management-Tenant': String(tenant) } });

function receipts(ids: number[], data: { items: WireItem[] }): DepartmentReceipt[] {
  return ids.map(departmentId => {
    const matches = data.items.filter(item => item.department_id === departmentId);
    const item = matches.length === 1 ? matches[0] : undefined;
    const failed = item?.admission === 'conflict' || ['failed', 'manual_review'].includes(item?.state ?? '');
    const confirmed = item?.operation_id && item.state === 'succeeded' && item.authorization === 'confirmed';
    return { departmentId, status: failed ? 'failed' : confirmed ? 'confirmed' : 'unconfirmed' };
  });
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
const PREVIEW_KEYS = ['summary_model_id', 'embedding_model_id', 'vision_model_id', 'chunk_size', 'overlap'] as const;

export async function listProviderModels(tenant: number): Promise<ProviderModels> {
  const data: Record<string, unknown> = await axios.get(`/api/v1/knowledge/space/provider-models`, pinned(tenant));
  const usable = (m: any, embedding: boolean) => [m?.id, m?.name, m?.display_name].every(v => typeof v === 'string' && v)
    && (!embedding || (Number.isSafeInteger(m.dimension) && m.dimension > 0));
  const kinds = ['chat', 'embedding', 'vision'] as const;
  if (!kinds.every(kind => Array.isArray(data?.[kind]) && (data[kind] as unknown[]).every(m => usable(m, kind === 'embedding')))) {
    throw new Error('Invalid model list');
  }
  return data as ProviderModels;
}

export async function listExtractTemplates(tenant: number): Promise<ExtractTemplate[]> {
  const data: unknown = await axios.get(`/api/v1/knowledge/space/provider-extract-templates`, pinned(tenant));
  if (!Array.isArray(data) || !data.every((row: any) => typeof row?.id === 'string' && row.id && typeof row?.name === 'string' && row.name)) {
    throw new Error('Invalid extract templates');
  }
  return data as ExtractTemplate[];
}

export async function previewDepartmentPreset(tenant: number, departmentId: number, selection: ProviderSelection): Promise<Record<string, unknown>> {
  const response: { preset_summary: Record<string, unknown> } = await axios.post(`${base}/provider-preview`, { department_id: departmentId, provider_selection: selection }, pinned(tenant));
  if (PREVIEW_KEYS.some(key => response.preset_summary?.[key] !== selection[key])) throw new Error('Unverified preset');
  return response.preset_summary;
}

export async function createExternalDepartmentBatch(tenant: number, ids: number[], key: string, preset: Record<string, unknown>, selection: ProviderSelection) {
  const result: { items: WireItem[] } = await axios.post(`${base}/batch-create`, {
    provider_key: 'weknora', request_key: key, preset_summary: preset, provider_selection: selection, items: ids.map(department_id => ({ department_id })),
  }, pinned(tenant));
  return receipts(ids, result);
}

export async function getExternalDepartmentBatchStatus(tenant: number, ids: number[], key: string) {
  const result: { items: WireItem[] } = await axios.post(`${base}/batch-status`, {request_key: key, department_ids: ids}, pinned(tenant));
  return receipts(ids, result);
}

// Hide (is_hidden=true) or restore (is_hidden=false) department knowledge spaces
// from the management list. Data, files and member permissions are preserved.
export async function setDepartmentKnowledgeSpacesVisibilityApi(
  departmentIds: number[],
  isHidden: boolean,
): Promise<{ changed: number }> {
  return await axios.post(`/api/v1/knowledge/space/department/visibility`, {
    department_ids: departmentIds,
    is_hidden: isHidden,
  });
}
