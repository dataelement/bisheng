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

export async function previewDepartmentPreset(tenant: number, departmentId: number): Promise<Record<string, unknown>> {
  const response: { preset_summary: Record<string, unknown> } = await axios.post(`${base}/provider-preview`, { department_id: departmentId }, pinned(tenant));
  return response.preset_summary;
}

export async function createExternalDepartmentBatch(tenant: number, ids: number[], key: string, preset: Record<string, unknown>) {
  const result: { items: WireItem[] } = await axios.post(`${base}/batch-create`, {
    provider_key: 'weknora', request_key: key, preset_summary: preset, items: ids.map(department_id => ({ department_id })),
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
