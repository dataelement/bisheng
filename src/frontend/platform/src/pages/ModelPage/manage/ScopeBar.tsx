import { notification, Select } from '@bisheng/ui';
// Page-level admin-scope switcher for LLM management.
//
// v2.5.1: scope was originally exposed as a global HeaderTenantScope
// dropdown. A product review concluded scope only meaningfully affects
// /api/v1/llm — roles use a global-view + field-filter pattern, audit logs
// rely on visible_tenant_ids for child-admin isolation. The switcher now
// lives on this page so its visible affordance matches where it changes
// data. Renders nothing for non-super-admin users.

import { useEffect, useId, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { useQueryClient } from "@tanstack/react-query"

import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels"
import { getTenantsApi } from "@/controllers/API/tenant"
import { useAdminScope } from "@/hooks/useAdminScope"
import { Tenant } from "@/types/api/tenant"
import { User } from "@/types/api/user"
import { displayTenantName } from "@/utils/tenantDisplayName"
import { isGlobalSuperUser } from "./permissions"

interface ScopeBarProps {
    user: User
    onScopeChange?: () => void | Promise<void>
}

const ROOT_TENANT_ID = 1

export function ScopeBar({ user, onScopeChange }: ScopeBarProps): JSX.Element | null {
    if (!isGlobalSuperUser(user)) {
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
        getTenantsApi({ page: 1, page_size: 100, status: "active" })
            .then((res) => {
                if (cancelled) return
                setTenants(res.data || [])
            })
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

    // The "no scope" entry historically rendered as "全树（默认）". Per
    // product feedback, surface the actual Root tenant name (matching how
    // child entries are labelled) for visual consistency. Falls back to
    // the old i18n string while the tenant list is still loading.
    const rootTenant = useMemo(
        () => tenants.find((row) => row.id === ROOT_TENANT_ID),
        [tenants],
    )
    const rootLabel = useMemo(() => {
        if (rootTenant) {
            return displayTenantName(rootTenant.tenant_name) || rootTenant.tenant_code
        }
        return t("tenant.adminScope.global")
    }, [rootTenant, t])

    const handleSelect = async (next: number | null) => {
        if (scopeLoading) return
        if (next === scope.scope_tenant_id) return
        try {
            await setScope(next)
            // Invalidate other react-query caches that surface llm-tenant
            // -aware data (e.g. ModelSelect dropdowns).
            await queryClient.invalidateQueries()
            await onScopeChange?.()
            notification.open({ type: "success", description: String(next === null
                    ? t("tenant.adminScope.cleared")
                    : t("tenant.adminScope.switched", {
                        name: tenants.find((r) => r.id === next)?.tenant_name || "",
                    }) ?? '') })
        } catch {
            // request interceptor will surface the error toast
        }
    }

    const options = useMemo(() => {
        const list = [
            // The "no scope" entry is the Root tenant; it stands for scope_tenant_id = null.
            { value: ROOT_TENANT_ID, label: rootLabel, disabled: false },
            ...tenants
                .filter((row) => row.id !== ROOT_TENANT_ID && row.id != null)
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
    }, [tenants, rootLabel, scope.scope_tenant_id, t])

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
                value={scope.scope_tenant_id ?? ROOT_TENANT_ID}
                loading={tenantsLoading}
                disabled={scopeLoading}
                onChange={(value) => {
                    if (value == null) return
                    const next = Number(value)
                    void handleSelect(next === ROOT_TENANT_ID ? null : next)
                }}
            />
        </div>
    )
}
