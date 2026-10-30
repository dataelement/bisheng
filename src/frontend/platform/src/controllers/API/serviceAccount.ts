import axios from "@/controllers/request";
import type {
  ApiKeyIssueForm,
  ApiKeyIssued,
  ApiKeyItem,
  ApiKeyPage,
  ApiKeyUpdateForm,
  DelegateScopeInput,
  OpenApiScopeCatalog,
  ServiceAccountForm,
  ServiceAccountDeleteResult,
  ServiceAccountGrantableResource,
  ServiceAccountItem,
  ServiceAccountPage,
  ServiceAccountResourceGrant,
} from "@/types/api/openApi";
import type {
  MutateResourceGrantsRequest,
  MutateResourceGrantsResult,
} from "./permission";

export interface ServiceAccountRequestScope {
  readonly tenantId: number | null;
  readonly signal: AbortSignal;
  readonly onScopeChanged: () => void;
}

export interface ServiceAccountManagementScope {
  scope_tenant_id: number | null;
  expires_at?: string | null;
}

export interface ServiceAccountOwnerCandidate {
  user_id: number;
  user_name: string;
  tenant_id: number;
}

async function scopedRequest<T>(
  scope: ServiceAccountRequestScope | undefined,
  run: (config: {
    headers?: Record<string, string>;
    signal?: AbortSignal;
  }) => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const sources = [scope?.signal, signal].filter(
    (item): item is AbortSignal => !!item,
  );
  const abort = () => controller.abort();
  sources.forEach((item) =>
    item.addEventListener("abort", abort, { once: true }),
  );
  if (sources.some((item) => item.aborted)) controller.abort();
  try {
    if (controller.signal.aborted)
      throw Object.assign(new Error("Canceled"), { code: "ERR_CANCELED" });
    const result = await run({
      headers: scope
        ? { "X-Service-Account-Tenant": scope.tenantId === null ? "all" : String(scope.tenantId) }
        : undefined,
      signal: controller.signal,
    });
    // An already accepted request may complete after a scope change.
    if (controller.signal.aborted)
      throw Object.assign(new Error("Canceled"), { code: "ERR_CANCELED" });
    return result;
  } catch (error) {
    if (
      !controller.signal.aborted &&
      typeof error === "object" &&
      error !== null &&
      "status_code" in error &&
      error.status_code === 26073
    )
      scope?.onScopeChanged();
    throw error;
  } finally {
    sources.forEach((item) => item.removeEventListener("abort", abort));
  }
}

export async function getServiceAccountManagementScopeApi(): Promise<ServiceAccountManagementScope> {
  return await axios.get("/api/v1/service-accounts/management-scope");
}

export async function setServiceAccountManagementScopeApi(
  tenantId: number,
): Promise<ServiceAccountManagementScope> {
  return await axios.put("/api/v1/service-accounts/management-scope", {
    tenant_id: tenantId,
  });
}

export async function listServiceAccountOwnerCandidatesApi(
  params: { keyword?: string; page: number; page_size: number },
  scope?: ServiceAccountRequestScope,
  signal?: AbortSignal,
): Promise<{ data: ServiceAccountOwnerCandidate[]; total: number }> {
  return scopedRequest(
    scope,
    (config) =>
      axios.get("/api/v1/service-accounts/owner-candidates", {
        ...config,
        params,
      }),
    signal,
  );
}

export async function listServiceAccountsApi(
  params: {
    keyword?: string;
    page: number;
    page_size: number;
  },
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountPage> {
  return scopedRequest(scope, (config) =>
    axios.get("/api/v1/service-accounts", { ...config, params, silent: true }),
  );
}

export async function createServiceAccountApi(
  data: ServiceAccountForm,
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountItem> {
  return scopedRequest(scope, (config) =>
    axios.post("/api/v1/service-accounts", data, config),
  );
}

export async function getServiceAccountApi(
  id: number,
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountItem> {
  return scopedRequest(scope, (config) =>
    axios.get(`/api/v1/service-accounts/${id}`, config),
  );
}

export async function updateServiceAccountApi(
  id: number,
  data: Partial<ServiceAccountForm>,
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountItem> {
  return scopedRequest(scope, (config) =>
    axios.patch(`/api/v1/service-accounts/${id}`, data, config),
  );
}

export async function setServiceAccountEnabledApi(
  id: number,
  enabled: boolean,
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountItem> {
  return scopedRequest(scope, (config) =>
    axios.post(
      `/api/v1/service-accounts/${id}/${enabled ? "enable" : "disable"}`,
      undefined,
      config,
    ),
  );
}

export async function deleteServiceAccountApi(
  id: number,
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountDeleteResult> {
  return scopedRequest(scope, (config) =>
    axios.delete(`/api/v1/service-accounts/${id}`, config),
  );
}

export async function listOpenApiScopesApi(): Promise<OpenApiScopeCatalog> {
  return await axios.get("/api/v1/service-accounts/scopes");
}

export async function listServiceAccountKeysApi(
  id: number,
  scope?: ServiceAccountRequestScope,
): Promise<ApiKeyItem[]> {
  return scopedRequest(scope, (config) =>
    axios.get(`/api/v1/service-accounts/${id}/keys`, config),
  );
}

export async function listServiceAccountKeysPageApi(
  id: number,
  params: { page: number; page_size: number },
  scope?: ServiceAccountRequestScope,
): Promise<ApiKeyPage> {
  return scopedRequest(scope, (config) =>
    axios.get(`/api/v1/service-accounts/${id}/keys/page`, {
      ...config,
      params,
      silent: true,
    }),
  );
}

export async function filterDelegateCandidatesApi(
  id: number,
  candidates: DelegateScopeInput[],
  signal?: AbortSignal,
  scope?: ServiceAccountRequestScope,
): Promise<DelegateScopeInput[]> {
  return scopedRequest(
    scope,
    (config) =>
      axios.post(
        `/api/v1/service-accounts/${id}/delegate-candidates:filter`,
        candidates,
        { ...config },
      ),
    signal,
  );
}

export async function issueServiceAccountKeyApi(
  id: number,
  data: ApiKeyIssueForm,
  scope?: ServiceAccountRequestScope,
): Promise<ApiKeyIssued> {
  return scopedRequest(scope, (config) =>
    axios.post(`/api/v1/service-accounts/${id}/keys`, data, config),
  );
}

export async function updateServiceAccountKeyApi(
  id: number,
  keyId: number,
  data: ApiKeyUpdateForm,
  scope?: ServiceAccountRequestScope,
): Promise<ApiKeyItem> {
  return scopedRequest(scope, (config) =>
    axios.patch(`/api/v1/service-accounts/${id}/keys/${keyId}`, data, config),
  );
}

export async function revokeServiceAccountKeyApi(
  id: number,
  keyId: number,
  scope?: ServiceAccountRequestScope,
): Promise<ApiKeyItem> {
  return scopedRequest(scope, (config) =>
    axios.post(
      `/api/v1/service-accounts/${id}/keys/${keyId}/revoke`,
      undefined,
      config,
    ),
  );
}

export async function revokeAllServiceAccountKeysApi(
  id: number,
  scope?: ServiceAccountRequestScope,
): Promise<{ revoked: number }> {
  return scopedRequest(scope, (config) =>
    axios.post(
      `/api/v1/service-accounts/${id}/keys/revoke-all`,
      undefined,
      config,
    ),
  );
}

export async function listServiceAccountResourceGrantsApi(
  id: number,
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountResourceGrant[]> {
  return scopedRequest(scope, (config) =>
    axios.get(`/api/v1/service-accounts/${id}/resource-grants`, config),
  );
}

export async function listServiceAccountGrantableResourcesApi(
  id: number,
  params: { resource_type?: string; keyword?: string },
  scope?: ServiceAccountRequestScope,
): Promise<ServiceAccountGrantableResource[]> {
  return scopedRequest(scope, (config) =>
    axios.get(`/api/v1/service-accounts/${id}/grantable-resources`, {
      ...config,
      params,
    }),
  );
}

export async function mutateServiceAccountResourceGrantsApi(
  id: number,
  resourceType: string,
  resourceId: string,
  data: MutateResourceGrantsRequest,
  scope?: ServiceAccountRequestScope,
): Promise<MutateResourceGrantsResult> {
  return scopedRequest(scope, (config) =>
    axios.post(`/api/v1/service-accounts/${id}/resource-grants:mutate`, data, {
      ...config,
      params: { resource_type: resourceType, resource_id: resourceId },
    }),
  );
}
