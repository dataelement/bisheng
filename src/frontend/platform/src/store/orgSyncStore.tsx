import { create } from "zustand"

import {
  createOrgSyncConfigApi,
  deleteOrgSyncConfigApi,
  executeOrgSyncApi,
  getOrgSyncLogsApi,
  listOrgSyncConfigsApi,
  testOrgSyncConnectionApi,
  updateOrgSyncConfigApi,
} from "@/controllers/API/orgSync"
import {
  OrgSyncConfig,
  OrgSyncConfigCreate,
  OrgSyncConfigUpdate,
  OrgSyncLog,
  OrgSyncProvider,
  OrgSyncTestResult,
} from "@/types/api/orgSync"

// Providers the "组织同步" UI is designed to manage end-to-end. Other rows
// (e.g. F014's SSO HMAC seed with provider='sso_realtime' and empty
// auth_config) live in the same org_sync_config table but are owned by
// different subsystems and must stay out of this list.
const USER_MANAGED_PROVIDERS: ReadonlySet<OrgSyncProvider> = new Set([
  "wecom",
  "feishu",
  "dingtalk",
  "generic_api",
])

interface OrgSyncState {
  // List state
  configs: OrgSyncConfig[]
  loading: boolean
  // Dialog / edit state
  editingConfig: OrgSyncConfig | null
  editLoading: boolean
  // Logs
  logs: OrgSyncLog[]
  logTotal: number
  logsLoading: boolean
  // Errors — consumers show toast via captureAndAlertRequestErrorHoc
  lastError: string | null

  fetchConfigs: () => Promise<void>
  createConfig: (data: OrgSyncConfigCreate) => Promise<OrgSyncConfig>
  updateConfig: (
    configId: number,
    data: OrgSyncConfigUpdate
  ) => Promise<OrgSyncConfig>
  deleteConfig: (configId: number) => Promise<void>
  testConnection: (configId: number) => Promise<OrgSyncTestResult>
  executeSync: (configId: number) => Promise<void>
  fetchLogs: (configId: number, page?: number, limit?: number) => Promise<void>

  setEditingConfig: (c: OrgSyncConfig | null) => void
  clearLogs: () => void
  resetError: () => void
}

export const useOrgSyncStore = create<OrgSyncState>((set, get) => ({
  configs: [],
  loading: false,
  editingConfig: null,
  editLoading: false,
  logs: [],
  logTotal: 0,
  logsLoading: false,
  lastError: null,

  fetchConfigs: async () => {
    set({ loading: true, lastError: null })
    try {
      const all = await listOrgSyncConfigsApi()
      const configs = all.filter((c) =>
        USER_MANAGED_PROVIDERS.has(c.provider)
      )
      set({ configs, loading: false })
    } catch (err: any) {
      set({ loading: false, lastError: String(err) })
      throw err
    }
  },

  createConfig: async (data) => {
    set({ editLoading: true, lastError: null })
    try {
      const config = await createOrgSyncConfigApi(data)
      await get().fetchConfigs()
      set({ editLoading: false, editingConfig: null })
      return config
    } catch (err: any) {
      set({ editLoading: false, lastError: String(err) })
      throw err
    }
  },

  updateConfig: async (configId, data) => {
    set({ editLoading: true, lastError: null })
    try {
      const config = await updateOrgSyncConfigApi(configId, data)
      await get().fetchConfigs()
      set({ editLoading: false, editingConfig: null })
      return config
    } catch (err: any) {
      set({ editLoading: false, lastError: String(err) })
      throw err
    }
  },

  deleteConfig: async (configId) => {
    set({ loading: true, lastError: null })
    try {
      await deleteOrgSyncConfigApi(configId)
      await get().fetchConfigs()
    } catch (err: any) {
      set({ loading: false, lastError: String(err) })
      throw err
    }
  },

  testConnection: async (configId) => {
    return await testOrgSyncConnectionApi(configId)
  },

  executeSync: async (configId) => {
    await executeOrgSyncApi(configId)
    // Optimistic mark as running in the list
    set((state) => ({
      configs: state.configs.map((c) =>
        c.id === configId ? { ...c, sync_status: "running" } : c
      ),
    }))
  },

  fetchLogs: async (configId, page = 1, limit = 20) => {
    set({ logsLoading: true, lastError: null })
    try {
      const { data, total } = await getOrgSyncLogsApi(configId, { page, limit })
      set({ logs: data, logTotal: total, logsLoading: false })
    } catch (err: any) {
      set({ logsLoading: false, lastError: String(err) })
      throw err
    }
  },

  setEditingConfig: (c) => set({ editingConfig: c }),
  clearLogs: () => set({ logs: [], logTotal: 0 }),
  resetError: () => set({ lastError: null }),
}))
