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

// ── Helpers ──────────────────────────────────────────
// Client request layer returns the full backend envelope {status_code, status_message, data}.
// All functions below unwrap .data so callers get the payload directly.

function unwrap<T>(res: any): T {
  return res?.data ?? res;
}

// ── Permission APIs ──────────────────────────────────

export async function getResourcePermissions(
  resourceType: string,
  resourceId: string
): Promise<PermissionEntry[]> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/permissions`
  );
  return unwrap(res);
}

export async function authorizeResource(
  resourceType: string,
  resourceId: string,
  grants: GrantItem[],
  revokes: RevokeItem[]
): Promise<null> {
  const res = await request.post(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/authorize`,
    { grants, revokes }
  );
  return unwrap(res);
}

export async function checkPermission(
  objectType: string,
  objectId: string,
  relation: string
): Promise<{ allowed: boolean }> {
  const res = await request.post(`/api/v1/permissions/check`, {
    object_type: objectType,
    object_id: objectId,
    relation,
  });
  return unwrap(res);
}

export async function getGrantableRelationModels(
  objectType: string,
  objectId: string
): Promise<RelationModel[]> {
  const res = await request.get(`/api/v1/permissions/relation-models/grantable`, {
    params: { object_type: objectType, object_id: objectId },
  });
  return unwrap(res);
}

// ── Subject search APIs ──────────────────────────────

export async function searchUsers(
  name: string,
  config?: { signal?: AbortSignal }
): Promise<{ data: { user_id: number; user_name: string }[]; total: number }> {
  const res = await request.get(`/api/v1/user/list`, {
    params: { name, page_num: 1, page_size: 200 },
    ...config,
  });
  return unwrap(res);
}

export async function getDepartmentTree(
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(`/api/v1/departments/tree`, config);
  return unwrap(res);
}

export async function getUserGroups(
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(`/api/v1/group/list`, config);
  const data = unwrap<any>(res);
  const rows = data?.records ?? data;
  return Array.isArray(rows) ? rows : [];
}
