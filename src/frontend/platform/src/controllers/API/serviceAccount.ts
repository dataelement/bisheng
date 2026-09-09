import axios from "@/controllers/request"
import type {
  ApiKeyIssueForm,
  ApiKeyIssued,
  ApiKeyItem,
  ApiKeyUpdateForm,
  OpenApiScopeCatalog,
  ServiceAccountForm,
  ServiceAccountDeleteResult,
  ServiceAccountGrantableResource,
  ServiceAccountItem,
  ServiceAccountPage,
  ServiceAccountResourceGrant,
} from "@/types/api/openApi"
import type {
  MutateResourceGrantsRequest,
  MutateResourceGrantsResult,
} from "./permission"

export async function listServiceAccountsApi(params: {
  keyword?: string
  page: number
  page_size: number
}): Promise<ServiceAccountPage> {
  return await axios.get("/api/v1/service-accounts", { params })
}

export async function createServiceAccountApi(data: ServiceAccountForm): Promise<ServiceAccountItem> {
  return await axios.post("/api/v1/service-accounts", data)
}

export async function getServiceAccountApi(id: number): Promise<ServiceAccountItem> {
  return await axios.get(`/api/v1/service-accounts/${id}`)
}

export async function updateServiceAccountApi(
  id: number,
  data: Partial<ServiceAccountForm>,
): Promise<ServiceAccountItem> {
  return await axios.patch(`/api/v1/service-accounts/${id}`, data)
}

export async function setServiceAccountEnabledApi(
  id: number,
  enabled: boolean,
): Promise<ServiceAccountItem> {
  return await axios.post(`/api/v1/service-accounts/${id}/${enabled ? "enable" : "disable"}`)
}

export async function deleteServiceAccountApi(id: number): Promise<ServiceAccountDeleteResult> {
  return await axios.delete(`/api/v1/service-accounts/${id}`)
}

export async function listOpenApiScopesApi(): Promise<OpenApiScopeCatalog> {
  return await axios.get("/api/v1/service-accounts/scopes")
}

export async function listServiceAccountKeysApi(id: number): Promise<ApiKeyItem[]> {
  return await axios.get(`/api/v1/service-accounts/${id}/keys`)
}

export async function issueServiceAccountKeyApi(
  id: number,
  data: ApiKeyIssueForm,
): Promise<ApiKeyIssued> {
  return await axios.post(`/api/v1/service-accounts/${id}/keys`, data)
}

export async function updateServiceAccountKeyApi(
  id: number,
  keyId: number,
  data: ApiKeyUpdateForm,
): Promise<ApiKeyItem> {
  return await axios.patch(`/api/v1/service-accounts/${id}/keys/${keyId}`, data)
}

export async function revokeServiceAccountKeyApi(id: number, keyId: number): Promise<ApiKeyItem> {
  return await axios.post(`/api/v1/service-accounts/${id}/keys/${keyId}/revoke`)
}

export async function revokeAllServiceAccountKeysApi(id: number): Promise<{ revoked: number }> {
  return await axios.post(`/api/v1/service-accounts/${id}/keys/revoke-all`)
}

export async function listServiceAccountResourceGrantsApi(
  id: number,
): Promise<ServiceAccountResourceGrant[]> {
  return await axios.get(`/api/v1/service-accounts/${id}/resource-grants`)
}

export async function listServiceAccountGrantableResourcesApi(
  id: number,
  params: { resource_type?: string; keyword?: string },
): Promise<ServiceAccountGrantableResource[]> {
  return await axios.get(`/api/v1/service-accounts/${id}/grantable-resources`, { params })
}

export async function mutateServiceAccountResourceGrantsApi(
  id: number,
  resourceType: string,
  resourceId: string,
  data: MutateResourceGrantsRequest,
): Promise<MutateResourceGrantsResult> {
  return await axios.post(`/api/v1/service-accounts/${id}/resource-grants:mutate`, data, {
    params: { resource_type: resourceType, resource_id: resourceId },
  })
}
