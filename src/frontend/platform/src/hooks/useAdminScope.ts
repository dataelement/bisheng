// React hook wrapping the admin-scope HTTP contract. Only the global
// super admin may set a scope; callers should pass `enabled: false` for
// non-super users so the initial GET does not produce a noisy 403.

import { useCallback, useEffect, useState } from "react"
import {
    AdminScopeResponse,
    getTenantScope,
    setTenantScope,
} from "@/controllers/API/admin"

export interface UseAdminScopeOptions {
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

function sameScope(a: AdminScopeResponse, b: AdminScopeResponse): boolean {
    return a.scope_tenant_id === b.scope_tenant_id && a.expires_at === b.expires_at
}

export function useAdminScope(options?: UseAdminScopeOptions): UseAdminScopeResult {
    const enabled = options?.enabled ?? true
    const [scope, setScopeState] = useState<AdminScopeResponse>(EMPTY_SCOPE)
    const [loading, setLoading] = useState<boolean>(false)

    const refresh = useCallback(async (): Promise<void> => {
        if (!enabled) return
        setLoading(true)
        try {
            const next = await getTenantScope()
            setScopeState(prev => (sameScope(prev, next) ? prev : next))
        } finally {
            setLoading(false)
        }
    }, [enabled])

    const setScope = useCallback(async (tenantId: number | null): Promise<void> => {
        if (!enabled) return
        setLoading(true)
        try {
            const next = await setTenantScope(tenantId)
            setScopeState(prev => (sameScope(prev, next) ? prev : next))
        } finally {
            setLoading(false)
        }
    }, [enabled])

    useEffect(() => {
        if (enabled) void refresh()
    }, [enabled, refresh])

    return { scope, loading, setScope, refresh }
}
