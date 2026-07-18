// Page-level admin-scope switcher for LLM management.
//
// v2.5.1: scope was originally exposed as a global HeaderTenantScope
// dropdown. A product review concluded scope only meaningfully affects
// /api/v1/llm — roles use a global-view + field-filter pattern, audit logs
// rely on visible_tenant_ids for child-admin isolation. The switcher now
// lives on this page so its visible affordance matches where it changes
// data. Renders nothing for non-super-admin users.

import { ChevronDown } from "lucide-react"
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
import { toast } from "@/components/bs-ui/toast/use-toast"
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
        return t("tenant.adminScope.global", { defaultValue: "全树（默认）" })
    }, [rootTenant, t])

    const currentLabel = useMemo(() => {
        if (scope.scope_tenant_id === null) {
            return rootLabel
        }
        const hit = tenants.find((row) => row.id === scope.scope_tenant_id)
        if (!hit) {
            return t("tenant.adminScope.loading", { defaultValue: "加载中..." })
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
            toast({
                variant: "success",
                description: next === null
                    ? t("tenant.adminScope.cleared", { defaultValue: "已恢复全树视图" })
                    : t("tenant.adminScope.switched", {
                        defaultValue: "已切换管理视图",
                        name: tenants.find((r) => r.id === next)?.tenant_name || "",
                    }),
            })
        } catch {
            // request interceptor will surface the error toast
        }
    }

    const childTenants = tenants.filter((row) => row.id !== ROOT_TENANT_ID)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    className="h-9 px-3 bg-secondary rounded-md flex items-center justify-center cursor-pointer hover:bg-secondary/80 transition-colors"
                    title={t("tenant.adminScope.label", { defaultValue: "管理视图" }) + ": " + currentLabel}
                    disabled={scopeLoading}
                >
                    <span className="text-xs text-muted-foreground mr-1">
                        {t("tenant.adminScope.label", { defaultValue: "管理视图" })}：
                    </span>
                    <span className="text-sm max-w-32 truncate">{currentLabel}</span>
                    <ChevronDown className="ml-1 w-4 h-4" />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-[180px]">
                <DropdownMenuLabel>
                    {t("tenant.adminScope.label", { defaultValue: "管理视图" })}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => handleSelect(null)}>
                    {scope.scope_tenant_id === null ? "✓ " : ""}
                    {rootLabel}
                </DropdownMenuItem>
                {tenantsLoading && (
                    <DropdownMenuItem disabled>
                        {t("tenant.adminScope.loading", { defaultValue: "加载中..." })}
                    </DropdownMenuItem>
                )}
                {!tenantsLoading && childTenants.length === 0 && (
                    <DropdownMenuItem disabled>
                        {t("tenant.adminScope.noChild", { defaultValue: "暂无子租户" })}
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
