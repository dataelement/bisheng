// F020-llm-tenant-isolation — reusable tenant-scope selector for admin pages.
//
// The component is a thin wrapper around the bs-ui Tabs primitive. It is
// intentionally dumb: it displays a list of tenant options, fires
// `onChange` with the chosen value, and respects a `disabled` state.
// Owning state (current scope, tenant options, admin identity) lives in
// the hosting page so the selector can be reused across ModelPage (F020),
// RolesPage, QuotaPage, and AuditLogPage without coupling to a specific
// data shape.
//
// Callers typically pair this with `useAdminScope` (F020 T13) and a
// `useUser` hook; pages render the selector only when
// `user.is_global_super` so Child Admins never see the switcher.

import * as React from "react"
import {
    Tabs,
    TabsList,
    TabsTrigger,
} from "@/components/bs-ui/tabs"

// `'global'` represents "no scope" — the super admin sees the whole tree.
// All other values are numeric tenant ids (Root = 1, Child = N).
export type AdminScopeValue = number | "global"

export interface TenantOption {
    value: AdminScopeValue
    label: string
}

export interface AdminScopeSelectorProps {
    value: AdminScopeValue
    tenants: TenantOption[]
    onChange: (value: AdminScopeValue) => void
    disabled?: boolean
}

function parseValue(raw: string): AdminScopeValue {
    if (raw === "global") {
        return "global"
    }
    const n = Number(raw)
    return Number.isNaN(n) ? "global" : n
}

export function AdminScopeSelector({
    value,
    tenants,
    onChange,
    disabled,
}: AdminScopeSelectorProps): JSX.Element {
    const handleValueChange = React.useCallback(
        (raw: string): void => {
            if (disabled) {
                return
            }
            onChange(parseValue(raw))
        },
        [disabled, onChange]
    )

    return (
        <Tabs value={String(value)} onValueChange={handleValueChange}>
            <TabsList>
                {tenants.map((t) => (
                    <TabsTrigger
                        key={String(t.value)}
                        value={String(t.value)}
                        disabled={disabled}
                    >
                        {t.label}
                    </TabsTrigger>
                ))}
            </TabsList>
        </Tabs>
    )
}
