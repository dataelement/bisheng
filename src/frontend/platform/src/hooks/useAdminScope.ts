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

export interface UseAdminScopeOptions {
    /**
     * Set to false to skip the initial GET and all network traffic.
     * Pages hosting the hook should pass `user.is_global_super` so
     * Child Admins and ordinary users never produce a 403 on mount.
     * Defaults to true so existing call sites keep working.
     */
    enabled?: boolean
}

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

export function useAdminScope(options?: UseAdminScopeOptions): UseAdminScopeResult {
    const enabled = options?.enabled ?? true
    const [scope, setScopeState] = useState<AdminScopeResponse>(EMPTY_SCOPE)
    const [loading, setLoading] = useState<boolean>(false)

    const refresh = useCallback(async (): Promise<void> => {
        if (!enabled) return
        setLoading(true)
        try {
            setScopeState(await getTenantScope())
        } finally {
            setLoading(false)
        }
    }, [enabled])

    const setScope = useCallback(async (tenantId: number | null): Promise<void> => {
        if (!enabled) return
        setLoading(true)
        try {
            setScopeState(await setTenantScope(tenantId))
        } finally {
            setLoading(false)
        }
    }, [enabled])

    useEffect(() => {
        // Kick off the initial read on mount iff enabled. Errors
        // propagate to the global axios interceptor.
        if (enabled) void refresh()
    }, [enabled, refresh])

    return { scope, loading, setScope, refresh }
}
