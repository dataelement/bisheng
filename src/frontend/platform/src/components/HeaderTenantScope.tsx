import { notification, Select } from '@bisheng/ui';
// One persisted management view across all platform modules.

import { useEffect, useId, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { useQueryClient } from "@tanstack/react-query"

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels"
import { getTenantsApi } from "@/controllers/API/tenant"
import { useAdminScope } from "@/hooks/useAdminScope"
import { Tenant } from "@/types/api/tenant"
import { User } from "@/types/api/user"
import { displayTenantName } from "@/utils/tenantDisplayName"


interface HeaderTenantScopeProps {
    user: User
    onScopeChange?: () => void | Promise<void>
}


export function HeaderTenantScope({ user, onScopeChange }: HeaderTenantScopeProps): JSX.Element | null {
    if (!user?.is_global_super) {
        return null
    }
    return <SuperAdminScopeSwitcher onScopeChange={onScopeChange} />
}

function SuperAdminScopeSwitcher({
    onScopeChange,
}: {
    onScopeChange?: () => void | Promise<void>
}): JSX.Element {
    const { t } = useTranslation("bs")
    const selectLabels = useSelectLabels()
    const labelId = useId()
    const queryClient = useQueryClient()
    const { scope, loading: scopeLoading, setScope } = useAdminScope()
    const [tenants, setTenants] = useState<Tenant[]>([])
    const [tenantsLoading, setTenantsLoading] = useState(false)

    useEffect(() => {
        let cancelled = false
        setTenantsLoading(true)
        const loadTenants = async () => {
            const rows: Tenant[] = []
            for (let page = 1; !cancelled; page++) {
                const res = await getTenantsApi({ page, page_size: 100, status: "active" })
                rows.push(...(res.data || []))
                if (!res.data?.length || rows.length >= res.total) break
            }
            if (!cancelled) setTenants(rows)
        }
        loadTenants()
            .catch(() => {
                if (cancelled) return
                setTenants([])
            })
            .finally(() => {
                if (!cancelled) setTenantsLoading(false)
            })
        return () => {
            cancelled = true
        }
    }, [])

    const handleSelect = async (next: number) => {
        if (scopeLoading) return
        if (next === scope.scope_tenant_id) return
        try {
            await setScope(next)
            // Invalidate other react-query caches that surface llm-tenant
            // -aware data (e.g. ModelSelect dropdowns).
            queryClient.clear()
            // Reload effect-owned pages as well as query caches; discard old forms.
            if (onScopeChange) await onScopeChange()
            else window.location.reload()
            notification.open({ type: "success", description: String(t("tenant.adminScope.switched", {
                        name: tenants.find((r) => r.id === next)?.tenant_name || "",
                    }) ?? '') })
        } catch {
            // request interceptor will surface the error toast
        }
    }

    const options = useMemo(() => {
        const list = [
            ...tenants
                .filter((row) => row.id != null && String(row.id) !== "" && Number.isSafeInteger(row.id) && row.id > 0 && row.status === "active")
                .map((row) => ({
                    value: row.id,
                    label: displayTenantName(row.tenant_name) || row.tenant_code,
                    disabled: false,
                })),
        ]
        // The current scope may point at a tenant the list has not returned
        // (yet): keep a readable label in the trigger instead of a bare id.
        const current = scope.scope_tenant_id
        if (current !== null && !list.some((option) => option.value === current)) {
            list.push({ value: current, label: t("tenant.adminScope.loading"), disabled: true })
        }
        return list
    }, [tenants, scope.scope_tenant_id, t])

    return (
        <div className="flex items-center gap-2">
            <span id={labelId} className="shrink-0 text-sm text-text-2">
                {t("tenant.adminScope.label")}
            </span>
            <Select
                {...selectLabels}
                aria-labelledby={labelId}
                className="w-48"
                options={options}
                value={scope.scope_tenant_id ?? undefined}
                loading={tenantsLoading}
                disabled={scopeLoading}
                onChange={(value) => {
                    if (value == null) return
                    const next = Number(value)
                    if (Number.isSafeInteger(next) && next > 0) void handleSelect(next)
                }}
            />
        </div>
    )
}
