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

interface PermissionRequestConfig {
  signal?: AbortSignal;
}

const PERMISSION_CHECK_CACHE_TTL_MS = 5_000;
const permissionCheckCache = new Map<string, {
  expiresAt: number;
  result: { allowed: boolean };
}>();
const permissionCheckInFlight = new Map<string, Promise<{ allowed: boolean }>>();
let permissionCheckCacheRevision = 0;

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

function permissionCheckKey(
  objectType: string,
  objectId: string,
  relation: string,
  permissionId?: string,
) {
  return [objectType, objectId, relation, permissionId ?? ""].join(":");
}

function createAbortError() {
  if (typeof DOMException !== "undefined") {
    return new DOMException("The operation was aborted.", "AbortError");
  }
  const error = new Error("The operation was aborted.");
  error.name = "AbortError";
  return error;
}

function withCallerAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(createAbortError());

  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(createAbortError());
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => {
      signal.removeEventListener("abort", onAbort);
    });
  });
}

function clearPermissionCheckCacheForResource(resourceType: string, resourceId: string) {
  permissionCheckCacheRevision += 1;
  const prefix = `${resourceType}:${resourceId}:`;
  for (const key of Array.from(permissionCheckCache.keys())) {
    if (key.startsWith(prefix)) permissionCheckCache.delete(key);
  }
  for (const key of Array.from(permissionCheckInFlight.keys())) {
    if (key.startsWith(prefix)) permissionCheckInFlight.delete(key);
  }
}

export function __clearPermissionCheckCacheForTests() {
  permissionCheckCacheRevision += 1;
  permissionCheckCache.clear();
  permissionCheckInFlight.clear();
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
  const data = unwrap<null>(res);
  clearPermissionCheckCacheForResource(resourceType, resourceId);
  return data;
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
  if (requestConfig?.signal?.aborted) {
    throw createAbortError();
  }
  const key = permissionCheckKey(objectType, objectId, relation, permissionId);
  const cached = permissionCheckCache.get(key);

  if (cached && cached.expiresAt > Date.now()) {
    return cached.result;
  }
  if (cached) {
    permissionCheckCache.delete(key);
  }

  let requestPromise = permissionCheckInFlight.get(key);
  if (!requestPromise) {
    const requestRevision = permissionCheckCacheRevision;
    requestPromise = request.post(`/api/v1/permissions/check`, {
      object_type: objectType,
      object_id: objectId,
      relation,
      permission_id: permissionId,
    }, withPermissionRequestOptions())
      .then((res) => {
        const result = unwrap<{ allowed: boolean }>(res);
        if (requestRevision === permissionCheckCacheRevision) {
          permissionCheckCache.set(key, {
            expiresAt: Date.now() + PERMISSION_CHECK_CACHE_TTL_MS,
            result,
          });
        }
        return result;
      })
      .finally(() => {
        if (permissionCheckInFlight.get(key) === requestPromise) {
          permissionCheckInFlight.delete(key);
        }
      });
    permissionCheckInFlight.set(key, requestPromise);
  }

  return withCallerAbort(requestPromise, requestConfig?.signal);
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

export async function getResourceGrantUsers(
  resourceType: ResourceType,
  resourceId: string,
  params?: { keyword?: string; page?: number; page_size?: number },
  config?: { signal?: AbortSignal }
): Promise<{ user_id: number; user_name: string }[]> {
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
): Promise<{ user_id: number; user_name: string }[]> {
  return getResourceGrantUsers("knowledge_space", resourceId, params, config);
}

export async function getResourceGrantDepartments(
  resourceType: ResourceType,
  resourceId: string,
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/departments`,
    withPermissionRequestOptions(config)
  );
  return unwrapArray(res);
}

export async function getKnowledgeSpaceGrantDepartments(
  resourceId: string,
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(
    `/api/v1/permissions/knowledge-spaces/${resourceId}/grant-subjects/departments`,
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

export async function getResourceGrantUserGroups(
  resourceType: ResourceType,
  resourceId: string,
  params?: { keyword?: string },
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(
    `/api/v1/permissions/resources/${resourceType}/${resourceId}/grant-subjects/user-groups`,
    {
      params: { keyword: params?.keyword ?? "" },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrapArray(res);
}

export async function getKnowledgeSpaceGrantUserGroups(
  resourceId: string,
  params?: { keyword?: string },
  config?: { signal?: AbortSignal }
): Promise<any[]> {
  const res = await request.get(
    `/api/v1/permissions/knowledge-spaces/${resourceId}/grant-subjects/user-groups`,
    {
      params: { keyword: params?.keyword ?? "" },
      ...withPermissionRequestOptions(config),
    }
  );
  return unwrapArray(res);
}
