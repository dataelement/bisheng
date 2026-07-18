/**
 * F017 SharedBadge — visual marker for "Group-shared Root resource".
 *
 * Rendered next to the resource name (list rows + detail header) when
 * the row carries `is_shared=true`. Tenant-aware: Root users see this
 * as a plain informational tag; Child users see it as the cue that the
 * resource is read-only for them (cannot edit / delete).
 *
 * The badge intentionally stays subtle (muted background, small font)
 * so it blends into the existing list density — not a call-to-action.
 */

import { useTranslation } from "react-i18next"
import { Badge } from "@/components/bs-ui/badge"

interface SharedBadgeProps {
    /** Only renders when `isShared=true`. Passing false/undefined returns null
     * so callers can render unconditionally: `<SharedBadge isShared={row.is_shared} />` */
    isShared?: boolean
    className?: string
}

export function SharedBadge({ isShared, className }: SharedBadgeProps) {
    const { t } = useTranslation()
    if (!isShared) return null
    return (
        <Badge
            variant="secondary"
            className={["text-xs px-1.5 py-0 font-normal", className]
                .filter(Boolean)
                .join(" ")}
            title={t("share.badgeTitle")}
        >
            {t("share.badge")}
        </Badge>
    )
}
