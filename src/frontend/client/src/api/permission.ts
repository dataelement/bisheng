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

export interface CreationPermissionContext {
  catalog_release_id: number;
  can_configure_initial_permissions: boolean;
  grantable_models: GrantablePermissionModel[];
}

export interface InitialPermissionGrant {
  model_key: string;
  subject: PermissionGrantSubjectInput;
}

export interface InitialPermissionsPayload {
  expected_catalog_release_id: number;
  grants: InitialPermissionGrant[];
}

export interface RawInitialPermissionResult {
  status: "succeeded" | "failed";
  resource_version?: number | null;
  assignee_ids?: string[];
  error_code?: number | null;
  message?: string | null;
}

export interface InitialPermissionResult {
  status: "succeeded" | "failed";
  resourceVersion?: number;
  assigneeIds: string[];
  errorCode: number | null;
  message?: string;
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

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" ? value as JsonRecord : null;
}

function assertSuccess(res: unknown) {
  const record = asRecord(res);
  if (record && "status_code" in record && record.status_code !== 200) {
    throw new Error(String(record.status_message || `Permission request failed: ${record.status_code}`));
  }
}

function unwrap<T>(res: unknown): T {
  assertSuccess(res);
  const record = asRecord(res);
  return (record && "data" in record ? record.data : res) as T;
}

function unwrapArray<T>(res: unknown): T[] {
  const data = unwrap<unknown>(res);
  const record = asRecord(data);
  const rows = record?.data ?? record?.list ?? record?.records ?? data;
  return Array.isArray(rows) ? rows : [];
}

function withPermissionRequestOptions(config?: PermissionRequestConfig) {
  return {
    skip403Redirect: true,
    ...config,
  };
}

export function mapInitialPermissionResult(
  result?: RawInitialPermissionResult | null,
): InitialPermissionResult | undefined {
  if (!result) return undefined;
  return {
    status: result.status,
    ...(result.resource_version == null
      ? {}
      : { resourceVersion: result.resource_version }),
    assigneeIds: result.assignee_ids ?? [],
    errorCode: result.error_code ?? null,
    ...(result.message ? { message: result.message } : {}),
  };
}

type CreationResourceType = "knowledge_space" | "channel";

function creationPermissionPath(resourceType: CreationResourceType): string {
  return resourceType === "knowledge_space"
    ? "/api/v1/knowledge/space"
    : "/api/v1/channel/manager";
}

export async function getCreationPermissionContext(
  resourceType: CreationResourceType,
  config?: PermissionRequestConfig,
): Promise<CreationPermissionContext> {
  const res = await request.get(
    `${creationPermissionPath(resourceType)}/creation-permission-context`,
    withPermissionRequestOptions(config),
  );
  return unwrap(res);
}

export async function searchCreationUsers(
  resourceType: CreationResourceType,
  name: string,
  params?: { page?: number; pageSize?: number },
  config?: PermissionRequestConfig,
): Promise<{ data: GrantUser[]; total: number }> {
  const res = await request.get(
    `${creationPermissionPath(resourceType)}/creation-grant-subjects/users`,
    {
      params: {
        keyword: name,
        page: params?.page ?? 1,
        page_size: params?.pageSize ?? 50,
      },
      ...withPermissionRequestOptions(config),
    },
  );
  const data = unwrap<unknown>(res);
  const record = asRecord(data);
  const rows = record?.data ?? data;
  const list = Array.isArray(rows) ? rows : [];
  return { data: list as GrantUser[], total: Number(record?.total ?? list.length) };
}

export async function getCreationDepartmentChildren(
  resourceType: CreationResourceType,
  parentId: number | null,
  config?: PermissionRequestConfig,
): Promise<GrantDepartmentNode[]> {
  const res = await request.get(
    `${creationPermissionPath(resourceType)}/creation-grant-subjects/departments/children`,
    {
      params: { parent_id: parentId ?? undefined },
      ...withPermissionRequestOptions(config),
    },
  );
  return unwrapArray<GrantDepartmentNode>(res);
}

export async function searchCreationDepartments(
  resourceType: CreationResourceType,
  keyword: string,
  limit = 50,
  config?: PermissionRequestConfig,
): Promise<GrantDepartmentSearchResult> {
  const res = await request.get(
    `${creationPermissionPath(resourceType)}/creation-grant-subjects/departments/search`,
    {
      params: { keyword, limit },
      ...withPermissionRequestOptions(config),
    },
  );
  return unwrap(res);
}

export async function getCreationUserGroups(
  resourceType: CreationResourceType,
  config?: PermissionRequestConfig,
): Promise<{ id: number; group_name: string }[]> {
  const res = await request.get(
    `${creationPermissionPath(resourceType)}/creation-grant-subjects/user-groups`,
    {
      params: { page: 1, page_size: 200 },
      ...withPermissionRequestOptions(config),
    },
  );
  const data = unwrap<unknown>(res);
  const record = asRecord(data);
  const rows = record?.data ?? data;
  return Array.isArray(rows)
    ? rows.map((row) => {
        const item = asRecord(row) ?? {};
        return { id: Number(item.id), group_name: String(item.name ?? item.group_name ?? "") };
      })
    : [];
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

export async function getAllResourcePermissionGrants(
  resourceType: ResourceType,
  resourceId: string,
  config?: PermissionRequestConfig,
): Promise<PermissionGrantAssignee[]> {
  const items: PermissionGrantAssignee[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | null = null;

  for (;;) {
    const page = await getResourcePermissionGrants(
      resourceType,
      resourceId,
      { cursor, page_size: 200 },
      config,
    );
    items.push(...page.data);
    if (!page.has_more) return items;
    if (!page.next_cursor || seenCursors.has(page.next_cursor)) {
      throw new Error("Permission roster pagination returned an invalid cursor");
    }
    seenCursors.add(page.next_cursor);
    cursor = page.next_cursor;
  }
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

// Scoped to the resource, not to the org chart: "who may be granted THIS
// resource" is answered by holding manage_permission on it, while the user-admin
// list answers "whom do I administer" — which a space manager may not be at all,
// so it came back empty for exactly the people allowed to grant.
export async function searchUsers(
  resourceType: ResourceType,
  resourceId: string,
  name: string,
  params?: { page?: number; pageSize?: number },
  config?: { signal?: AbortSignal }
): Promise<{ data: GrantUser[]; total: number }> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/users`,
    {
      params: {
        keyword: name,
        page: params?.page ?? 1,
        page_size: params?.pageSize ?? 50,
      },
      ...withPermissionRequestOptions(config),
    }
  );
  const data = unwrap<unknown>(res);
  const record = asRecord(data);
  const rows = record?.data ?? data;
  const list = Array.isArray(rows) ? rows : [];
  return { data: list as GrantUser[], total: Number(record?.total ?? list.length) };
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
  resourceType: ResourceType,
  resourceId: string,
  parentId: number | null,
  config?: { signal?: AbortSignal }
): Promise<GrantDepartmentNode[]> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/departments/children`,
    {
      params: { parent_id: parentId ?? undefined },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrapArray<GrantDepartmentNode>(res);
}

export async function searchDepartments(
  resourceType: ResourceType,
  resourceId: string,
  keyword: string,
  limit = 50,
  config?: { signal?: AbortSignal }
): Promise<GrantDepartmentSearchResult> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/departments/search`,
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
  resourceType: ResourceType,
  resourceId: string,
  config?: { signal?: AbortSignal }
): Promise<{ id: number; group_name: string }[]> {
  const res = await request.get(
    `${permissionResourcePath(resourceType, resourceId)}/grant-subjects/user-groups`,
    {
      params: { page: 1, page_size: 200 },
      ...withPermissionRequestOptions(config),
    }
  );
  const data = unwrap<unknown>(res);
  const record = asRecord(data);
  const rows = record?.data ?? data;
  return Array.isArray(rows)
    ? rows.map((row) => {
        const item = asRecord(row) ?? {};
        return { id: Number(item.id), group_name: String(item.name ?? item.group_name ?? "") };
      })
    : [];
}
