/**
 * F017 ShareToChildrenSwitch — Root-only "share with subsidiaries" toggle.
 *
 * Renders nothing when the caller is NOT a global super admin. Admin flag
 * is read from the user store so every resource create form can drop this
 * component in without wiring that auth check itself. The underlying
 * Switch is the project-standard Radix wrapper so keyboard/focus parity
 * with other toggles is preserved.
 *
 * Two render modes:
 *   - Create form: no initial fetch; the switch's `checked` state feeds
 *     the create request body.
 *   - Detail page: parent owns the real value + a confirmation callback
 *     when turning OFF (AC-05 cancel-share guard).
 *
 * i18n keys live in the `bs` namespace — see T27 for the three locales.
 */

import { useTranslation } from "react-i18next"
import { Switch } from "@/components/bs-ui/switch"
import { Label } from "@/components/bs-ui/label"
import { useUserStore } from "@/store/userStore"

interface ShareToChildrenSwitchProps {
    /** Current share state (controlled). Use `undefined` to inherit the
     * backend default (`Root.share_default_to_children`) in create mode. */
    checked?: boolean
    /** Called with the new checked state. In detail mode the parent
     * should trigger `bsConfirm` before actually PATCH-ing off. */
    onCheckedChange: (checked: boolean) => void
    /** Optional override when the default hidden rule does not apply
     * (e.g. the 5.2.1 mount dialog's "auto_distribute" checkbox reuses
     * this component for visual consistency). */
    forceVisible?: boolean
    /** Disables interaction (e.g. while an API call is in flight). */
    disabled?: boolean
    className?: string
}

export function ShareToChildrenSwitch({
    checked,
    onCheckedChange,
    forceVisible = false,
    disabled = false,
    className,
}: ShareToChildrenSwitchProps) {
    const { t } = useTranslation()
    const user = useUserStore((state: any) => state.user)

    // F017 D6: only the global super admin sees this toggle. Child users
    // can never share their resources, and surfacing a disabled toggle
    // would be visual noise. Project convention: `user.role === "admin"`
    // (see MainLayout, SystemPage) — do NOT check a non-existent user_role.
    const isSuperAdmin = user?.role === "admin"
    if (!isSuperAdmin && !forceVisible) {
        return null
    }

    return (
        <div
            className={["flex items-center justify-between gap-3 py-2", className]
                .filter(Boolean)
                .join(" ")}
        >
            <div className="flex flex-col">
                <Label className="text-sm font-medium">
                    {t("share.toChildrenLabel")}
                </Label>
                <span className="text-xs text-gray-500">
                    {t("share.toChildrenHint")}
                </span>
            </div>
            <Switch
                checked={Boolean(checked)}
                onCheckedChange={onCheckedChange}
                disabled={disabled}
            />
        </div>
    )
}
