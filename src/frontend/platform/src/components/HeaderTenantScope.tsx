// Header tenant-scope switcher.
//
// - Global super admin: dropdown lets the operator pivot between "Full tree"
//   (no scope) and any active Child Tenant. Selecting an entry calls
//   `setTenantScope` then invalidates every react-query cache so the page
//   re-fetches under the new scope.
// - Everyone else (Child Admin, regular user): a read-only chip showing the
//   user's current leaf Tenant. They cannot switch, but the chip serves as an
//   identity cue ("which Tenant am I in?") consistent with v2.4 behaviour.
//
// The component lives in MainLayout so the switcher is reachable from every
// admin page (roles, audit, departments, LLM, ...).

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
import { Separator } from "@/components/bs-ui/separator"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { getTenantsApi } from "@/controllers/API/tenant"
import { useAdminScope } from "@/hooks/useAdminScope"
import { User } from "@/types/api/user"
import { Tenant } from "@/types/api/tenant"
import { displayTenantName } from "@/utils/tenantDisplayName"

interface HeaderTenantScopeProps {
    user: User
}

const ROOT_TENANT_ID = 1

function isGlobalSuper(user: User): boolean {
    // Backend already populates ``is_global_super`` on login; fall back to
    // role==='admin' for legacy sessions that predate F019.
    return Boolean(user.is_global_super) || user.role === "admin"
}

export function HeaderTenantScope({ user }: HeaderTenantScopeProps): JSX.Element | null {
    if (isGlobalSuper(user)) {
        return (
            <>
                <SuperAdminScopeSwitcher />
                <Separator className="mx-[4px] dark:bg-[#111111]" orientation="vertical" />
            </>
        )
    }
    return <ReadOnlyLeafTenantChip user={user} />
}

function ReadOnlyLeafTenantChip({ user }: { user: User }): JSX.Element | null {
    // Identity-only chip for Child Admins / regular users — no dropdown, no
    // tenant-list fetch, just "you are in <Tenant>". Falls back through
    // leaf_tenant_name → tenant_name → tenant_code so we always render
    // something meaningful when the multi-tenant header is enabled.
    const label =
        user.leaf_tenant_name ||
        (user as User & { tenant_name?: string }).tenant_name ||
        (user as User & { tenant_code?: string }).tenant_code ||
        ""
    if (!label) return null
    return (
        <>
            <div
                className="h-8 px-3 bg-header-icon rounded-lg my-4 flex items-center justify-center"
                title={label}
            >
                <span className="text-sm leading-8 max-w-32 truncate">{label}</span>
            </div>
            <Separator className="mx-[4px] dark:bg-[#111111]" orientation="vertical" />
        </>
    )
}

function SuperAdminScopeSwitcher(): JSX.Element {
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

    const currentLabel = useMemo(() => {
        if (scope.scope_tenant_id === null) {
            return t("tenant.adminScope.global", { defaultValue: "全树（默认）" })
        }
        const hit = tenants.find((row) => row.id === scope.scope_tenant_id)
        if (!hit) {
            // Tenant list still loading or scope points at an archived tenant
            return t("tenant.adminScope.loading", { defaultValue: "加载中..." })
        }
        return displayTenantName(hit.tenant_name) || hit.tenant_code
    }, [scope.scope_tenant_id, tenants, t])

    const handleSelect = async (next: number | null) => {
        if (scopeLoading) return
        if (next === scope.scope_tenant_id) return
        try {
            await setScope(next)
            // v2.5.1: scope 仅影响管理类 API 的 IN-list；切换后让所有 react-query
            // 缓存失效，当前页随之重新拉取，避免旧 scope 数据残留。
            await queryClient.invalidateQueries()
            // Pages that fetch via plain useState (not react-query) listen
            // to this event so they can reload manually.
            window.dispatchEvent(
                new CustomEvent("bisheng:admin-scope-changed", {
                    detail: { scopeTenantId: next },
                }),
            )
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
                    className="h-8 px-3 bg-header-icon rounded-lg my-4 flex items-center justify-center cursor-pointer"
                    title={t("tenant.adminScope.label", { defaultValue: "管理视图" }) + ": " + currentLabel}
                    disabled={scopeLoading}
                >
                    <span className="text-xs text-muted-foreground mr-1">
                        {t("tenant.adminScope.label", { defaultValue: "管理视图" })}：
                    </span>
                    <span className="text-sm leading-8 max-w-32 truncate">{currentLabel}</span>
                    <ChevronDown className="ml-1 w-4 h-4" />
                </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[180px]">
                <DropdownMenuLabel>
                    {t("tenant.adminScope.label", { defaultValue: "管理视图" })}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => handleSelect(null)}>
                    {scope.scope_tenant_id === null ? "✓ " : ""}
                    {t("tenant.adminScope.global", { defaultValue: "全树（默认）" })}
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
