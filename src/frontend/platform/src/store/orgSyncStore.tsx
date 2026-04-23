import { create } from "zustand"

import { listGatewayOrgSyncLogsApi } from "@/controllers/API/orgSync"
import { OrgSyncLog } from "@/types/api/orgSync"

const PAGE_SIZE = 20

interface OrgSyncState {
  gatewayLogs: OrgSyncLog[]
  gatewayTotal: number
  loading: boolean
  page: number
  lastError: string | null

  fetchGatewayLogs: (page?: number) => Promise<void>
  resetError: () => void
}

export const useOrgSyncStore = create<OrgSyncState>((set, get) => ({
  gatewayLogs: [],
  gatewayTotal: 0,
  loading: false,
  page: 1,
  lastError: null,

  fetchGatewayLogs: async (pageArg) => {
    const page = pageArg ?? get().page
    set({ loading: true, lastError: null, page })
    try {
      const { data, total } = await listGatewayOrgSyncLogsApi({
        page,
        limit: PAGE_SIZE,
      })
      set({ gatewayLogs: data, gatewayTotal: total, loading: false })
    } catch (err: unknown) {
      set({ loading: false, lastError: String(err) })
      throw err
    }
  },

  resetError: () => set({ lastError: null }),
}))
