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
  | "dashboard";

export type RelationLevel = "owner" | "manager" | "editor" | "viewer";
export type SubjectType = "user" | "department" | "user_group";
export type CreationResourceType = "knowledge_space" | "channel";

export interface InitialPermissionsPayload {
  grants: GrantItem[];
}

export interface InitialPermissionResult {
  status: "success" | "failed";
  errorCode: number | null;
  directAppliedCount: number;
  inviteCreatedCount: number;
  inviteExistingCount: number;
  failedCount: number;
  results: AuthorizationItemOutcome[];
}

export interface RawInitialPermissionResult {
  status: "success" | "failed";
  error_code?: number | null;
  direct_applied_count?: number;
  invite_created_count?: number;
  invite_existing_count?: number;
  failed_count?: number;
  results?: RawAuthorizationItemOutcome[];
}

export type AuthorizationOutcome =
  | "applied"
  | "invite_created"
  | "invite_existing"
  | "failed";

export interface AuthorizationItemOutcome {
  operation: "grant" | "revoke";
  subjectType: SubjectType;
  subjectId: number;
  relation: RelationLevel;
  modelId: string | null;
  outcome: AuthorizationOutcome;
  approvalInstanceId: number | null;
  errorCode: number | null;
  errorMessage: string | null;
}

export interface RawAuthorizationItemOutcome {
  operation: "grant" | "revoke";
  subject_type: SubjectType;
  subject_id: number;
  relation: RelationLevel;
  model_id?: string | null;
  outcome: AuthorizationOutcome;
  approval_instance_id?: number | null;
  error_code?: number | null;
  error_message?: string | null;
}

export interface AuthorizationResult {
  syncedUserCount: number;
  affectedMemberCount: number;
  directAppliedCount: number;
  inviteCreatedCount: number;
  inviteExistingCount: number;
  failedCount: number;
  results: AuthorizationItemOutcome[];
}

export interface RawAuthorizationResult {
  synced_user_count?: number;
  affected_member_count?: number;
  direct_applied_count?: number;
  invite_created_count?: number;
  invite_existing_count?: number;
  failed_count?: number;
  results?: RawAuthorizationItemOutcome[];
}

export interface PermissionEntry {
  subject_type: SubjectType;
  subject_id: number;
  subject_name: string | null;
  subject_group_names?: string[];
  subject_member_names?: string[];
  relation: RelationLevel;
  model_id?: string;
  model_name?: string;
  include_children?: boolean;
  /** Channel creator: permission level is permanent and not editable. */
  is_creator?: boolean;
  authorizationStatus?: "active" | "pending";
  approvalInstanceId?: number | null;
  authorization_status?: "active" | "pending";
  approval_instance_id?: number | null;
}

export interface GrantItem {
  subject_type: SubjectType;
  subject_id: number;
  relation: RelationLevel;
  model_id?: string;
  include_children?: boolean;
}

function authorizationOutcomeMatchesGrant(
  outcome: AuthorizationItemOutcome,
  grant: GrantItem,
): boolean {
  return outcome.operation === "grant"
    && outcome.subjectType === grant.subject_type
    && outcome.subjectId === grant.subject_id
    && outcome.relation === grant.relation
    && (outcome.modelId ?? null) === (grant.model_id ?? null);
}

export function getFailedAuthorizationGrants(
  grants: GrantItem[],
  results: AuthorizationItemOutcome[],
): GrantItem[] {
  if (results.length === 0) return grants;
  const failed = results.filter((result) => result.outcome === "failed");
  return grants.filter((grant) => (
    failed.some((outcome) => authorizationOutcomeMatchesGrant(outcome, grant))
  ));
}

export type RevokeItem = Omit<GrantItem, "model_id">;

export interface RelationModel {
  id: string;
  name: string;
  relation: RelationLevel;
  grant_tier?: "owner" | "manager" | "usage";
  permissions: string[];
  permissions_explicit?: boolean;
  is_system: boolean;
}

export interface SelectedSubject {
  type: SubjectType;
  id: number;
  name: string;
  include_children?: boolean;
}

export interface PermissionRequestConfig {
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

export function mapInitialPermissionResult(
  result?: RawInitialPermissionResult | null,
): InitialPermissionResult | undefined {
  if (!result) return undefined;
  return {
    status: result.status,
    errorCode: result.error_code ?? null,
    directAppliedCount: result.direct_applied_count ?? 0,
    inviteCreatedCount: result.invite_created_count ?? 0,
    inviteExistingCount: result.invite_existing_count ?? 0,
    failedCount: result.failed_count ?? 0,
    results: (result.results ?? []).map(mapAuthorizationItemOutcome),
  };
}

function mapAuthorizationItemOutcome(
  result: RawAuthorizationItemOutcome,
): AuthorizationItemOutcome {
  return {
    operation: result.operation,
    subjectType: result.subject_type,
    subjectId: result.subject_id,
    relation: result.relation,
    modelId: result.model_id ?? null,
    outcome: result.outcome,
    approvalInstanceId: result.approval_instance_id ?? null,
    errorCode: result.error_code ?? null,
    errorMessage: result.error_message ?? null,
  };
}

export function mapAuthorizationResult(
  result?: RawAuthorizationResult | null,
): AuthorizationResult {
  return {
    syncedUserCount: result?.synced_user_count ?? 0,
    affectedMemberCount: result?.affected_member_count ?? 0,
    directAppliedCount: result?.direct_applied_count ?? 0,
    inviteCreatedCount: result?.invite_created_count ?? 0,
    inviteExistingCount: result?.invite_existing_count ?? 0,
    failedCount: result?.failed_count ?? 0,
    results: (result?.results ?? []).map(mapAuthorizationItemOutcome),
  };
}

function mapPermissionEntry(entry: PermissionEntry): PermissionEntry {
  return {
    ...entry,
    authorizationStatus: entry.authorization_status ?? entry.authorizationStatus ?? "active",
    approvalInstanceId: entry.approval_instance_id ?? entry.approvalInstanceId ?? null,
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
  return unwrapArray<PermissionEntry>(res).map(mapPermissionEntry);
}

export async function authorizeResource(
  resourceType: string,
  resourceId: string,
  grants: GrantItem[],
  revokes: RevokeItem[],
  config?: PermissionRequestConfig
): Promise<AuthorizationResult> {
  const res = await request.post(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/authorize`,
    { grants, revokes },
    withPermissionRequestOptions(config)
  );
  return mapAuthorizationResult(unwrap<RawAuthorizationResult | null>(res));
}

export async function checkPermission(
  objectType: string,
  objectId: string,
  relation: string,
  permissionIdOrConfig?: string | PermissionRequestConfig,
  config?: PermissionRequestConfig
): Promise<{ allowed: boolean }> {
  const permissionId =
    typeof permissionIdOrConfig === "string" ? permissionIdOrConfig : undefined;
  const requestConfig =
    typeof permissionIdOrConfig === "string" ? config : permissionIdOrConfig;
  const res = await request.post(`/api/v1/permissions/check`, {
    object_type: objectType,
    object_id: objectId,
    relation,
    permission_id: permissionId,
  }, withPermissionRequestOptions(requestConfig));
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

export async function getCreationGrantableRelationModels(
  objectType: CreationResourceType,
  config?: PermissionRequestConfig,
): Promise<RelationModel[]> {
  const res = await request.get(`/api/v1/permissions/relation-models/grantable`, {
    params: { object_type: objectType, creation: true },
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

export interface GrantUserGroup {
  id: number;
  group_name: string;
}

interface CreationGrantSubjectQueryBase {
  resourceType: CreationResourceType;
}

export interface CreationGrantUserQuery extends CreationGrantSubjectQueryBase {
  subjectType: "user";
  operation: "list";
  keyword?: string;
  page?: number;
  pageSize?: number;
}

export interface CreationGrantUserGroupQuery extends CreationGrantSubjectQueryBase {
  subjectType: "user_group";
  operation: "list";
  keyword?: string;
  page?: number;
  pageSize?: number;
}

export interface CreationGrantDepartmentChildrenQuery extends CreationGrantSubjectQueryBase {
  subjectType: "department";
  operation: "children";
  parentId?: number | null;
}

export interface CreationGrantDepartmentSearchQuery extends CreationGrantSubjectQueryBase {
  subjectType: "department";
  operation: "search";
  keyword: string;
  limit?: number;
}

export interface CreationGrantDepartmentPathTreeQuery extends CreationGrantSubjectQueryBase {
  subjectType: "department";
  operation: "path_tree";
  departmentId: number;
}

export interface CreationGrantUserTreeChildrenQuery extends CreationGrantSubjectQueryBase {
  subjectType: "user";
  operation: "tree_children";
  parentId?: number | null;
  page?: number;
  pageSize?: number;
}

export interface CreationGrantUserTreeSearchQuery extends CreationGrantSubjectQueryBase {
  subjectType: "user";
  operation: "tree_search";
  keyword: string;
  limit?: number;
}

export type CreationGrantSubjectsQuery =
  | CreationGrantUserQuery
  | CreationGrantUserGroupQuery
  | CreationGrantDepartmentChildrenQuery
  | CreationGrantDepartmentSearchQuery
  | CreationGrantDepartmentPathTreeQuery
  | CreationGrantUserTreeChildrenQuery
  | CreationGrantUserTreeSearchQuery;

export async function getResourceGrantUsers(
  resourceType: ResourceType,
  resourceId: string,
  params?: { keyword?: string; page?: number; page_size?: number },
  config?: { signal?: AbortSignal }
): Promise<GrantUser[]> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/users`,
    {
      params: {
        keyword: params?.keyword ?? "",
        page: params?.page ?? 1,
        page_size: params?.page_size ?? 2000,
      },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrapArray(res);
}

export async function getKnowledgeSpaceGrantUsers(
  resourceId: string,
  params?: { keyword?: string; page?: number; page_size?: number },
  config?: { signal?: AbortSignal }
): Promise<GrantUser[]> {
  return getResourceGrantUsers("knowledge_space", resourceId, params, config);
}

// ── Lazy grant-user tree (F038) ───────────────────────
// Department-tree user picker: one browse layer = child departments
// (navigation) + the direct primary-department users of the expanded node
// (leaves); search keeps the full ancestor path and attaches matched users to
// their primary department node. Mirrors the department tree below.

export async function getResourceGrantUserTreeChildren(
  resourceType: ResourceType,
  resourceId: string,
  parentId: number | null,
  params?: { userPage?: number; userPageSize?: number },
  config?: { signal?: AbortSignal }
): Promise<GrantUserTreeChildrenResult> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/users/tree/children`,
    {
      params: {
        parent_id: parentId ?? undefined,
        user_page: params?.userPage ?? 1,
        user_page_size: params?.userPageSize ?? 100,
      },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrap<GrantUserTreeChildrenResult>(res) ?? EMPTY_USER_TREE_CHILDREN;
}

export async function searchResourceGrantUserTree(
  resourceType: ResourceType,
  resourceId: string,
  keyword: string,
  limit = 50,
  config?: { signal?: AbortSignal }
): Promise<GrantDepartmentSearchResult> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/users/tree/search`,
    {
      params: { keyword, limit },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrap<GrantDepartmentSearchResult>(res) ?? EMPTY_DEPARTMENT_SEARCH_RESULT;
}

// ── Lazy grant-department tree (F038) ────────────────
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
  /** F038 user-tree only: direct primary-department members attached as leaves
   * (populated by the user-tree search endpoint; absent for department-only
   * browsing/search responses). */
  users?: GrantUser[];
}

export interface GrantDepartmentSearchResult {
  roots: GrantDepartmentNode[];
  total_matches: number;
  truncated: boolean;
}

/** F038 user-tree browse layer: child departments (navigation) + the direct
 * primary-department users of the expanded node (leaves), one page at a time. */
export interface GrantUserTreeChildrenResult {
  departments: GrantDepartmentNode[];
  users: GrantUser[];
  has_more_users: boolean;
}

const EMPTY_DEPARTMENT_SEARCH_RESULT: GrantDepartmentSearchResult = {
  roots: [],
  total_matches: 0,
  truncated: false,
};

const EMPTY_USER_TREE_CHILDREN: GrantUserTreeChildrenResult = {
  departments: [],
  users: [],
  has_more_users: false,
};

export function getCreationGrantSubjects(
  query: CreationGrantUserQuery,
  config?: PermissionRequestConfig,
): Promise<GrantUser[]>;
export function getCreationGrantSubjects(
  query: CreationGrantUserGroupQuery,
  config?: PermissionRequestConfig,
): Promise<GrantUserGroup[]>;
export function getCreationGrantSubjects(
  query: CreationGrantDepartmentChildrenQuery,
  config?: PermissionRequestConfig,
): Promise<GrantDepartmentNode[]>;
export function getCreationGrantSubjects(
  query: CreationGrantDepartmentSearchQuery | CreationGrantDepartmentPathTreeQuery,
  config?: PermissionRequestConfig,
): Promise<GrantDepartmentSearchResult>;
export function getCreationGrantSubjects(
  query: CreationGrantUserTreeChildrenQuery,
  config?: PermissionRequestConfig,
): Promise<GrantUserTreeChildrenResult>;
export function getCreationGrantSubjects(
  query: CreationGrantUserTreeSearchQuery,
  config?: PermissionRequestConfig,
): Promise<GrantDepartmentSearchResult>;
export async function getCreationGrantSubjects(
  query: CreationGrantSubjectsQuery,
  config?: PermissionRequestConfig,
): Promise<
  | GrantUser[]
  | GrantUserGroup[]
  | GrantDepartmentNode[]
  | GrantDepartmentSearchResult
  | GrantUserTreeChildrenResult
> {
  const params: Record<string, string | number> = {
    resource_type: query.resourceType,
    subject_type: query.subjectType,
    operation: query.operation,
  };
  if ("keyword" in query && query.keyword !== undefined) params.keyword = query.keyword;
  if ("page" in query && query.page !== undefined) params.page = query.page;
  if ("pageSize" in query && query.pageSize !== undefined) params.page_size = query.pageSize;
  if ("parentId" in query && query.parentId != null) params.parent_id = query.parentId;
  if ("departmentId" in query) params.department_id = query.departmentId;
  if ("limit" in query && query.limit !== undefined) params.limit = query.limit;

  const res = await request.get(`/api/v1/permissions/creation-grant-subjects`, {
    params,
    ...withPermissionRequestOptions(config),
  });
  if (query.subjectType === "department"
    && (query.operation === "search" || query.operation === "path_tree")) {
    return unwrap<GrantDepartmentSearchResult>(res) ?? EMPTY_DEPARTMENT_SEARCH_RESULT;
  }
  if (query.subjectType === "user") {
    if (query.operation === "list") return unwrapArray<GrantUser>(res);
    if (query.operation === "tree_children") {
      return unwrap<GrantUserTreeChildrenResult>(res) ?? EMPTY_USER_TREE_CHILDREN;
    }
    return unwrap<GrantDepartmentSearchResult>(res) ?? EMPTY_DEPARTMENT_SEARCH_RESULT;
  }
  if (query.subjectType === "user_group") return unwrapArray<GrantUserGroup>(res);
  return unwrapArray<GrantDepartmentNode>(res);
}

export async function getResourceGrantDepartmentChildren(
  resourceType: ResourceType,
  resourceId: string,
  parentId: number | null,
  config?: { signal?: AbortSignal }
): Promise<GrantDepartmentNode[]> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments/children`,
    {
      params: { parent_id: parentId ?? undefined },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrapArray<GrantDepartmentNode>(res);
}

export async function searchResourceGrantDepartments(
  resourceType: ResourceType,
  resourceId: string,
  keyword: string,
  limit = 50,
  config?: { signal?: AbortSignal }
): Promise<GrantDepartmentSearchResult> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments/search`,
    {
      params: { keyword, limit },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrap<GrantDepartmentSearchResult>(res) ?? EMPTY_DEPARTMENT_SEARCH_RESULT;
}

export async function getResourceGrantDepartmentPathTree(
  resourceType: ResourceType,
  resourceId: string,
  departmentId: number,
  config?: PermissionRequestConfig,
): Promise<GrantDepartmentSearchResult> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments/${departmentId}/path-tree`,
    withPermissionRequestOptions(config),
  );
  return unwrap<GrantDepartmentSearchResult>(res) ?? EMPTY_DEPARTMENT_SEARCH_RESULT;
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

export async function getResourceGrantUserGroups(
  resourceType: ResourceType,
  resourceId: string,
  params?: { keyword?: string },
  config?: { signal?: AbortSignal }
): Promise<GrantUserGroup[]> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/user-groups`,
    {
      params: { keyword: params?.keyword ?? "" },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrapArray<GrantUserGroup>(res);
}

export async function getKnowledgeSpaceGrantUserGroups(
  resourceId: string,
  params?: { keyword?: string },
  config?: { signal?: AbortSignal }
): Promise<GrantUserGroup[]> {
  return getResourceGrantUserGroups("knowledge_space", resourceId, params, config);
}
