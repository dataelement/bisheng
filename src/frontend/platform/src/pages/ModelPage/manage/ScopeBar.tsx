import { notification } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";
// Page-level admin-scope switcher for LLM management.
//
// v2.5.1: scope was originally exposed as a global HeaderTenantScope
// dropdown. A product review concluded scope only meaningfully affects
// /api/v1/llm — roles use a global-view + field-filter pattern, audit logs
// rely on visible_tenant_ids for child-admin isolation. The switcher now
// lives on this page so its visible affordance matches where it changes
// data. Renders nothing for non-super-admin users.

import { Button } from "@bisheng/ui"

import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { useQueryClient } from "react-query"

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/bs-ui/dropdownMenu"

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

    const currentLabel = useMemo(() => {
        if (scope.scope_tenant_id === null) {
            return rootLabel
        }
        const hit = tenants.find((row) => row.id === scope.scope_tenant_id)
        if (!hit) {
            return t("tenant.adminScope.loading")
        }
        return displayTenantName(hit.tenant_name) || hit.tenant_code
    }, [scope.scope_tenant_id, tenants, t, rootLabel])

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

    const childTenants = tenants.filter((row) => row.id !== ROOT_TENANT_ID)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    type="button"
                    variant="filled"
                    title={t("tenant.adminScope.label") + ": " + currentLabel}
                    disabled={scopeLoading} color="default"
                >
                    <span className="text-xs text-muted-foreground mr-1">
                        {t("tenant.adminScope.label")}{": "}
                    </span>
                    <span className="text-sm max-w-32 truncate">{currentLabel}</span>
                    <Outlined.Down className="ml-1 w-4 h-4" />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-[180px]">
                <DropdownMenuLabel>
                    {t("tenant.adminScope.label")}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => handleSelect(null)}>
                    {scope.scope_tenant_id === null ? "✓ " : ""}
                    {rootLabel}
                </DropdownMenuItem>
                {tenantsLoading && (
                    <DropdownMenuItem disabled>
                        {t("tenant.adminScope.loading")}
                    </DropdownMenuItem>
                )}
                {!tenantsLoading && childTenants.length === 0 && (
                    <DropdownMenuItem disabled>
                        {t("tenant.adminScope.noChild")}
                    </DropdownMenuItem>
                )}
                {childTenants.map((row) => (
                    <DropdownMenuItem
                        key={row.id}
                        onSelect={() => handleSelect(row.id)}
                    >
                        {scope.scope_tenant_id === row.id ? "✓ " : ""}
                        {displayTenantName(row.tenant_name) || row.tenant_code}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
