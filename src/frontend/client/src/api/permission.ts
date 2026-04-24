import request from "./request";

export type ResourceType =
  | "knowledge_space"
  | "folder"
  | "knowledge_file"
  | "workflow"
  | "assistant"
  | "tool"
  | "channel"
  | "dashboard";

export type RelationLevel = "owner" | "manager" | "editor" | "viewer";
export type SubjectType = "user" | "department" | "user_group";

export interface PermissionEntry {
  subject_type: SubjectType;
  subject_id: number;
  subject_name: string | null;
  relation: RelationLevel;
  model_id?: string;
  model_name?: string;
  include_children?: boolean;
}

export interface GrantItem {
  subject_type: SubjectType;
  subject_id: number;
  relation: RelationLevel;
  model_id?: string;
  include_children?: boolean;
}

export type RevokeItem = Omit<GrantItem, "model_id">;

export interface RelationModel {
  id: string;
  name: string;
  relation: RelationLevel;
  permissions: string[];
  is_system: boolean;
}

export interface SelectedSubject {
  type: SubjectType;
  id: number;
  name: string;
  include_children?: boolean;
}

interface PermissionRequestConfig {
  signal?: AbortSignal;
}

// ── Helpers ──────────────────────────────────────────
// Client request layer returns the full backend envelope {status_code, status_message, data}.
// All functions below unwrap .data so callers get the payload directly.

function unwrap<T>(res: any): T {
  return res?.data ?? res;
}

function unwrapArray<T = any>(res: any): T[] {
  const data = unwrap<any>(res);
  const rows = data?.data ?? data?.list ?? data?.records ?? data;
  return Array.isArray(rows) ? rows : [];
}

function withPermissionRequestOptions(config?: PermissionRequestConfig) {
  return {
    skip403Redirect: true,
    ...config,
  };
}

// ── Permission APIs ──────────────────────────────────

export async function getResourcePermissions(
  resourceType: string,
  resourceId: string,
  config?: PermissionRequestConfig
): Promise<PermissionEntry[]> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/permissions`,
    withPermissionRequestOptions(config)
  );
  return unwrapArray<PermissionEntry>(res);
}

export async function authorizeResource(
  resourceType: string,
  resourceId: string,
  grants: GrantItem[],
  revokes: RevokeItem[],
  config?: PermissionRequestConfig
): Promise<null> {
  const res = await request.post(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/authorize`,
    { grants, revokes },
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

export async function checkPermission(
  objectType: string,
  objectId: string,
  relation: string,
  config?: PermissionRequestConfig
): Promise<{ allowed: boolean }> {
  const res = await request.post(`/api/v1/permissions/check`, {
    object_type: objectType,
    object_id: objectId,
    relation,
  }, withPermissionRequestOptions(config));
  return unwrap(res);
}

export async function getGrantableRelationModels(
  objectType: string,
  objectId: string,
  config?: PermissionRequestConfig
): Promise<RelationModel[]> {
  const res = await request.get(`/api/v1/permissions/relation-models/grantable`, {
    params: { object_type: objectType, object_id: objectId },
    ...withPermissionRequestOptions(config),
  });
  return unwrapArray<RelationModel>(res);
}

export async function canOpenPermissionDialog(
  objectType: ResourceType,
  objectId: string,
  config?: PermissionRequestConfig
): Promise<boolean> {
  const models = await getGrantableRelationModels(
    objectType,
    objectId,
    config
  );
  return Array.isArray(models) && models.length > 0;
}

// ── Subject search APIs ──────────────────────────────

export async function searchUsers(
  name: string,
  config?: { signal?: AbortSignal }
): Promise<{ data: { user_id: number; user_name: string }[]; total: number }> {
  const res = await request.get(`/api/v1/user/list`, {
    params: { name, page_num: 1, page_size: 200 },
    ...withPermissionRequestOptions(config),
  });
  const data = unwrap<any>(res);
  const rows = data?.data ?? data?.list ?? data?.records ?? data;
  const list = Array.isArray(rows) ? rows : [];
  return {
    data: list,
    total: Number(data?.total ?? list.length),
  };
}

export async function getDepartmentTree(
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(
    `/api/v1/departments/tree`,
    withPermissionRequestOptions(config)
  );
  return unwrapArray(res);
}

export async function getUserGroups(
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(
    `/api/v1/group/list`,
    withPermissionRequestOptions(config)
  );
  const data = unwrap<any>(res);
  const rows = data?.records ?? data;
  return Array.isArray(rows) ? rows : [];
}
