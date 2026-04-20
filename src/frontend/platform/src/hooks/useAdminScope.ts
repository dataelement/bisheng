// F020-llm-tenant-isolation — React hook wrapping the F019 admin-scope
// HTTP contract. Used by `<AdminScopeSelector>` (F020 T14) and any other
// management page that needs to render or flip the caller's management-
// view scope (future: RolesPage / QuotaPage / AuditLogPage).
//
// Implementation notes:
// - Only the global super admin may set a scope. Child Admins / ordinary
//   users see HTTP 403 from the backend; callers should conditionally
//   render the selector only when `user.is_global_super` is true so
//   the initial GET doesn't produce a noisy 403 in the console.
// - `refresh` re-reads the current scope from the server. `setScope`
//   performs the POST and mirrors the resulting state locally so the
//   caller can update the UI without a second round-trip.
// - `loading` covers both the initial fetch and each `setScope` call.

import { useCallback, useEffect, useState } from "react"
import {
    AdminScopeResponse,
    getTenantScope,
    setTenantScope,
} from "@/controllers/API/admin"

export interface UseAdminScopeResult {
    scope: AdminScopeResponse
    loading: boolean
    setScope: (tenantId: number | null) => Promise<void>
    refresh: () => Promise<void>
}

const EMPTY_SCOPE: AdminScopeResponse = {
    scope_tenant_id: null,
    expires_at: null,
}

export function useAdminScope(): UseAdminScopeResult {
    const [scope, setScopeState] = useState<AdminScopeResponse>(EMPTY_SCOPE)
    const [loading, setLoading] = useState<boolean>(false)

    const refresh = useCallback(async (): Promise<void> => {
        setLoading(true)
        try {
            setScopeState(await getTenantScope())
        } finally {
            setLoading(false)
        }
    }, [])

    const setScope = useCallback(async (tenantId: number | null): Promise<void> => {
        setLoading(true)
        try {
            setScopeState(await setTenantScope(tenantId))
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        // Kick off the initial read on mount. Errors propagate to the
        // global axios interceptor (non-super callers see 403).
        void refresh()
    }, [refresh])

    return { scope, loading, setScope, refresh }
}
