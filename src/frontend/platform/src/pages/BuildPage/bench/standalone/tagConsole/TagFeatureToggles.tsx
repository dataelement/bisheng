import { Switch } from "@/components/bs-ui/switch"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { userContext } from "@/contexts/userContext"
import { getKnowledgeConfigApi, setKnowledgeConfigApi } from "@/controllers/API"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useCallback, useContext, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { resolveConfigEnvelope } from "../../ConfigInheritanceBanner"

/** The two tenant-level switches this page can change. */
type ToggleKey = "auto_tag_visible" | "review_tag_visible"

interface TagFeatureState {
    auto_tag_visible: boolean
    review_tag_visible: boolean
}

/**
 * The two switches from the workbench knowledge-space config, mirrored here.
 *
 * Labels are taken from that page rather than from the field names: the section
 * `auto_tag_visible` belongs to is called 标签库管理 there. Naming it after the
 * field ("自动打标") reads as a master switch for tagging, which it is not —
 * that mistake produced a bug report and a round of wrong fixes.
 *
 * Turning one off hides nothing on this page: an admin still has to be able to
 * clear leftover tags and work the pending queue afterwards.
 *
 * Only a tenant admin may change them (the config endpoint requires it), so for
 * anyone else the block is not rendered rather than rendered disabled — a
 * department admin can reach this page but has nothing to do with these.
 */
export function TagFeatureToggles() {
    const { t } = useTranslation()
    const { toast } = useToast()
    const { user } = useContext(userContext)
    const [state, setState] = useState<TagFeatureState | null>(null)
    const [saving, setSaving] = useState<ToggleKey | null>(null)

    // Matches the server's own gate (super admin or this tenant's child admin),
    // which is what the config endpoint checks.
    const canEdit = user?.role === "admin" || Boolean(user?.is_child_admin)

    useEffect(() => {
        if (!canEdit) return
        let cancelled = false
        getKnowledgeConfigApi()
            .then((res) => {
                if (cancelled) return
                const { data } = resolveConfigEnvelope<Record<string, unknown>>(res)
                setState({
                    // Absent means on: that is the schema default, and treating
                    // it as off would show every tenant a switch that lies.
                    auto_tag_visible: data?.auto_tag_visible !== false,
                    review_tag_visible: data?.review_tag_visible !== false,
                })
            })
            .catch(() => {
                // Read-only failure: leaving the block unrendered beats showing
                // switches whose position is a guess.
                if (!cancelled) setState(null)
            })
        return () => {
            cancelled = true
        }
    }, [canEdit])

    const persist = useCallback(
        async (key: ToggleKey, next: boolean) => {
            setSaving(key)
            // Read-modify-write, never a partial POST. The endpoint takes a whole
            // config object and fills anything absent with schema defaults, so
            // sending just this field would wipe the prompts and chunk size.
            const current = await captureAndAlertRequestErrorHoc(getKnowledgeConfigApi())
            const { data } = resolveConfigEnvelope<Record<string, unknown>>(current)
            if (!data) {
                setSaving(null)
                setState((prev) => (prev ? { ...prev, [key]: !next } : prev))
                return
            }
            const res = await captureAndAlertRequestErrorHoc(setKnowledgeConfigApi({ ...data, [key]: next }))
            setSaving(null)
            if (!res) {
                // Put the switch back where it was; the value never changed.
                setState((prev) => (prev ? { ...prev, [key]: !next } : prev))
                return
            }
            toast({ variant: "success", description: t("build.saved", "已保存") })
        },
        [t, toast],
    )

    // No confirmation step: the workbench page these came from has none, and
    // the switch itself plus the toast is the feedback. persist() rolls the
    // switch back if the write fails.
    const handleToggle = (key: ToggleKey, next: boolean) => {
        setState((prev) => (prev ? { ...prev, [key]: next } : prev))
        void persist(key, next)
    }

    if (!canEdit || !state) return null

    return (
        <div className="flex shrink-0 items-center gap-5">
            <label className="flex items-center gap-2 text-xs text-[#4E5969]">
                <span>{t("build.tagLibraryManagementTitle", "标签库管理")}</span>
                <Switch
                    checked={state.auto_tag_visible}
                    disabled={saving === "auto_tag_visible"}
                    onCheckedChange={(checked) => handleToggle("auto_tag_visible", checked)}
                />
            </label>
            <label className="flex items-center gap-2 text-xs text-[#4E5969]">
                <span>{t("build.autoTagGenerationTitle", "待审核标签")}</span>
                <Switch
                    checked={state.review_tag_visible}
                    disabled={saving === "review_tag_visible"}
                    onCheckedChange={(checked) => handleToggle("review_tag_visible", checked)}
                />
            </label>
        </div>
    )
}
