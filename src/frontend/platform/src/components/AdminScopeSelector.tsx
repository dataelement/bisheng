// Reusable tenant-scope selector for admin pages. Pair with
// `useAdminScope` and render only for the global super admin.

import * as React from "react"
import {
    Tabs,
    TabsList,
    TabsTrigger,
} from "@/components/bs-ui/tabs"

// `'global'` represents no scope (full tree); numbers are tenant ids.
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
