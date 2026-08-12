import request from "./request";

export type ResourceType =
  | "knowledge_space"
  | "knowledge_library"
  | "folder"
  | "knowledge_file"
  | "workflow"
  | "assistant"
  | "tool"
  | "channel"
  | "dashboard"
  | "linsight_skill";

export type SubjectType = "user" | "department" | "user_group";
export type PermissionActionLevel = 1 | 2 | 3 | 4;
export type ResourcePermissionMode = "INHERIT" | "CUSTOM";

export interface GrantablePermissionModel {
  key: string;
  name: string;
  level: PermissionActionLevel | null;
  active: boolean;
}

export interface ResourcePermissionContext {
  mode: ResourcePermissionMode;
  parent_type: ResourceType | null;
  parent_id: string | null;
  resource_version: number;
  catalog_release_id: number;
  projection_state: string;
  can_manage_permission: boolean;
}

export interface PermissionGrantSubject {
  type: SubjectType;
  id: string;
  name: string | null;
}

export interface PermissionGrantSource {
  type: string;
  include_children: boolean;
}

export interface PermissionGrantAssignee {
  assignee_id: string;
  assignee_version: number;
  subject: PermissionGrantSubject;
  model: GrantablePermissionModel;
  source: PermissionGrantSource;
  scope: "LOCAL" | "INHERITED";
  inherited_from: string | null;
  inherited_from_name?: string | null;
  protected: boolean;
  editable: boolean;
}

export interface PermissionGrantCursorPage {
  data: PermissionGrantAssignee[];
  page_size: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface MyResourcePermissions {
  mode: ResourcePermissionMode;
  actions: string[];
  sources: PermissionGrantSource[];
  roster_complete: boolean;
}

export interface PermissionGrantSubjectInput {
  type: SubjectType;
  id: string;
  userset_relation?: string | null;
  include_children?: boolean;
}

export type PermissionGrantMutationChange =
  | {
      op: "ADD";
      model_key: string;
      subject: PermissionGrantSubjectInput;
    }
  | {
      op: "MOVE";
      assignee_id: string;
      expected_assignee_version: number;
      target_model_key: string;
    }
  | {
      op: "REMOVE";
      assignee_id: string;
      expected_assignee_version: number;
    };

export interface MutateResourceGrantsRequest {
  idempotency_key: string;
  expected_resource_version: number;
  expected_catalog_release_id: number;
  changes: PermissionGrantMutationChange[];
}

export interface MutateResourceGrantsResult {
  resource_version: number;
  items: PermissionGrantAssignee[];
}

export interface CreatePermissionModeDraftRequest {
  target_mode: ResourcePermissionMode;
  expected_resource_version: number;
  expected_catalog_release_id: number;
}

export interface PermissionModeDraft {
  draft_id: string;
  target_mode: ResourcePermissionMode;
  impact_checksum: string;
  affected_assignees: number;
  expires_at: string;
}

export interface ApplyPermissionModeDraftRequest {
  idempotency_key: string;
  expected_resource_version: number;
  expected_catalog_release_id: number;
  confirmed: true;
}

export interface ApplyPermissionModeDraftResult {
  applied: boolean;
  mode: ResourcePermissionMode;
  resource_version: number;
}

export interface CheckResourceActionRequest {
  resource_type: ResourceType;
  resource_id: string;
  action: string;
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

function assertSuccess(res: any) {
  if (res && typeof res === "object" && "status_code" in res && res.status_code !== 200) {
    throw new Error(res.status_message || `Permission request failed: ${res.status_code}`);
  }
}

function unwrap<T>(res: any): T {
  assertSuccess(res);
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

function permissionResourcePath(
  resourceType: ResourceType,
  resourceId: string
): string {
  return `/api/v1/permissions/resources/${resourceType}/${resourceId}`;
}

export async function getResourcePermissionContext(
  resourceType: ResourceType,
  resourceId: string,
  config?: PermissionRequestConfig
): Promise<ResourcePermissionContext> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/context`,
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

export async function getResourcePermissionGrants(
  resourceType: ResourceType,
  resourceId: string,
  params: { cursor?: string | null; page_size?: number } = {},
  config?: PermissionRequestConfig
): Promise<PermissionGrantCursorPage> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/grants`,
    {
      params: {
        cursor: params.cursor ?? undefined,
        page_size: params.page_size ?? 50,
      },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrap(res);
}

export async function getMyResourcePermissions(
  resourceType: ResourceType,
  resourceId: string,
  config?: PermissionRequestConfig
): Promise<MyResourcePermissions> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/my-permissions`,
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

export async function getGrantablePermissionModels(
  resourceType: ResourceType,
  resourceId: string,
  config?: PermissionRequestConfig
): Promise<GrantablePermissionModel[]> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/grantable-models`,
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

export async function mutateResourceGrants(
  resourceType: ResourceType,
  resourceId: string,
  payload: MutateResourceGrantsRequest,
  config?: PermissionRequestConfig
): Promise<MutateResourceGrantsResult> {
  const res = await request.post(
    `${permissionResourcePath(resourceType, resourceId)}/grants:mutate`,
    payload,
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

export async function createResourcePermissionModeDraft(
  resourceType: ResourceType,
  resourceId: string,
  payload: CreatePermissionModeDraftRequest,
  config?: PermissionRequestConfig
): Promise<PermissionModeDraft> {
  const res = await request.post(
    `${permissionResourcePath(resourceType, resourceId)}/mode-drafts`,
    payload,
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

export async function applyResourcePermissionModeDraft(
  resourceType: ResourceType,
  resourceId: string,
  draftId: string,
  payload: ApplyPermissionModeDraftRequest,
  config?: PermissionRequestConfig
): Promise<ApplyPermissionModeDraftResult> {
  const res = await request.post(
    `${permissionResourcePath(resourceType, resourceId)}/mode-drafts/${draftId}/apply`,
    payload,
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

export async function checkResourceAction(
  payload: CheckResourceActionRequest,
  config?: PermissionRequestConfig
): Promise<{ allowed: boolean }> {
  const res = await request.post(
    "/api/v1/permissions/check",
    payload,
    withPermissionRequestOptions(config)
  );
  return unwrap(res);
}

// ── Subject search APIs ──────────────────────────────

/**
 * A grantable user candidate. The backend `grant-subjects/users` endpoint
 * (shared by knowledge spaces and channels) also returns the person id and
 * the user's primary department path, surfaced under the username in the picker.
 */
export interface GrantUser {
  user_id: number;
  user_name: string;
  external_id?: string | null;
  primary_department_path?: string | null;
}

export async function searchUsers(
  name: string,
  params?: { page?: number; pageSize?: number },
  config?: { signal?: AbortSignal }
): Promise<{ data: { user_id: number; user_name: string }[]; total: number }> {
  const res = await request.get(`/api/v1/user/list`, {
    params: {
      name,
      page_num: params?.page ?? 1,
      page_size: params?.pageSize ?? 50,
    },
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

// ── Lazy organization-department tree ────────────────
// Browse one visible layer / server search / locate-by-id, so a large org tree
// is never loaded at once. Same authorization scope as the full-tree endpoint
// above (tenant subtree minus child-tenant mounts). `path` is the materialized
// ancestor path (`/1/21/106/`, ending with the node's own id); `has_children`
// drives the expand arrow; `matched` flags search hits.

export interface GrantDepartmentNode {
  id: number;
  dept_id: string;
  name: string;
  parent_id: number | null;
  path: string;
  sort_order?: number;
  source?: string;
  status?: string;
  is_tenant_root?: boolean;
  mounted_tenant_id?: number | null;
  has_children?: boolean;
  matched?: boolean;
  children?: GrantDepartmentNode[];
}

export interface GrantDepartmentSearchResult {
  roots: GrantDepartmentNode[];
  total_matches: number;
  truncated: boolean;
}

const EMPTY_DEPARTMENT_SEARCH_RESULT: GrantDepartmentSearchResult = {
  roots: [],
  total_matches: 0,
  truncated: false,
};

export async function getDepartmentChildren(
  parentId: number | null,
  config?: { signal?: AbortSignal }
): Promise<GrantDepartmentNode[]> {
  const res = await request.get(
    `/api/v1/departments/children`,
    {
      params: { parent_id: parentId ?? undefined },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrapArray<GrantDepartmentNode>(res);
}

export async function searchDepartments(
  keyword: string,
  limit = 50,
  config?: { signal?: AbortSignal }
): Promise<GrantDepartmentSearchResult> {
  const res = await request.get(
    `/api/v1/departments/search`,
    {
      params: { keyword, limit },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrap<GrantDepartmentSearchResult>(res) ?? EMPTY_DEPARTMENT_SEARCH_RESULT;
}

// (no client consumer needs locate/path-tree: the picker browses+searches only,
// and the permission list reads the backend-resolved full-path subject_name.)

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
