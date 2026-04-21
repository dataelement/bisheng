import axios from "@/controllers/request"
import {
  OrgSyncConfig,
  OrgSyncConfigCreate,
  OrgSyncConfigUpdate,
  OrgSyncLog,
  OrgSyncLogPage,
  OrgSyncRemoteNode,
  OrgSyncTestResult,
} from "@/types/api/orgSync"

// Config CRUD — matches F009 9 endpoints.

export async function listOrgSyncConfigsApi(): Promise<OrgSyncConfig[]> {
  return await axios.get(`/api/v1/org-sync/configs`)
}

export async function getOrgSyncConfigApi(
  configId: number
): Promise<OrgSyncConfig> {
  return await axios.get(`/api/v1/org-sync/configs/${configId}`)
}

export async function createOrgSyncConfigApi(
  data: OrgSyncConfigCreate
): Promise<OrgSyncConfig> {
  return await axios.post(`/api/v1/org-sync/configs`, data)
}

export async function updateOrgSyncConfigApi(
  configId: number,
  data: OrgSyncConfigUpdate
): Promise<OrgSyncConfig> {
  return await axios.put(`/api/v1/org-sync/configs/${configId}`, data)
}

export async function deleteOrgSyncConfigApi(
  configId: number
): Promise<void> {
  return await axios.delete(`/api/v1/org-sync/configs/${configId}`)
}

// Execution.

export async function testOrgSyncConnectionApi(
  configId: number
): Promise<OrgSyncTestResult> {
  return await axios.post(`/api/v1/org-sync/configs/${configId}/test`)
}

export async function executeOrgSyncApi(
  configId: number
): Promise<{ config_id: number; message: string }> {
  return await axios.post(`/api/v1/org-sync/configs/${configId}/execute`)
}

export async function getOrgSyncLogsApi(
  configId: number,
  params: { page?: number; limit?: number } = {}
): Promise<OrgSyncLogPage> {
  return await axios.get(`/api/v1/org-sync/configs/${configId}/logs`, {
    params: { page: 1, limit: 20, ...params },
  })
}

export async function getOrgSyncRemoteTreeApi(
  configId: number
): Promise<OrgSyncRemoteNode[]> {
  return await axios.get(`/api/v1/org-sync/configs/${configId}/remote-tree`)
}
