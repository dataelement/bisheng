import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
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
 * Tenant-level feature switches, mirrored from the workbench config page.
 *
 * These are **not** display toggles for this page: `auto_tag_visible` decides
 * whether end users see the auto-tagging UI in a knowledge space, and
 * `review_tag_visible` decides whether AI tagging still produces pending tags at
 * all. Turning either off must therefore not hide anything here — an admin still
 * has to be able to clear leftover tags and finish the pending queue after the
 * feature is switched off.
 *
 * Only a tenant admin may change them (the config endpoint requires it), so for
 * anyone else the block is not rendered rather than rendered disabled: a
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
                // Read-only failure: leaving the block unrendered is better than
                // showing switches whose position is a guess.
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

    const handleToggle = (key: ToggleKey, next: boolean, offConfirm: string) => {
        if (next) {
            // Optimistic: the switch itself is the feedback, and persist() puts
            // it back if the write fails.
            setState((prev) => (prev ? { ...prev, [key]: true } : prev))
            void persist(key, true)
            return
        }
        // Switching off takes effect immediately and reaches beyond this page,
        // so unlike the config form — which has a save step to pause at — it
        // asks first.
        //
        // The switch is deliberately *not* flipped yet: the dialog can be
        // dismissed by cancel, by the close button or by the overlay, and only
        // the first of those reports back. Moving it after confirmation instead
        // means every dismissal leaves it showing the real setting.
        bsConfirm({
            title: t("prompt", "提示"),
            desc: offConfirm,
            okTxt: t("system.confirm", "确认"),
            canelTxt: t("cancel", { ns: "bs" }),
            onOk(close) {
                setState((prev) => (prev ? { ...prev, [key]: false } : prev))
                void persist(key, false)
                close?.()
            },
        })
    }

    if (!canEdit || !state) return null

    return (
        <div className="flex shrink-0 items-center gap-5">
            <label className="flex items-center gap-2 text-xs text-[#4E5969]">
                <span>{t("build.tagConsole.autoTagFeature", "自动打标")}</span>
                <Switch
                    checked={state.auto_tag_visible}
                    disabled={saving === "auto_tag_visible"}
                    onCheckedChange={(checked) =>
                        handleToggle(
                            "auto_tag_visible",
                            checked,
                            t(
                                "build.tagConsole.autoTagFeatureOffConfirm",
                                "关闭后，知识空间内的自动打标功能将对本租户所有用户隐藏。已有标签不受影响。确认关闭？",
                            ),
                        )
                    }
                />
            </label>
            <label className="flex items-center gap-2 text-xs text-[#4E5969]">
                <span>{t("build.tagConsole.reviewTagFeature", "待审核标签")}</span>
                <Switch
                    checked={state.review_tag_visible}
                    disabled={saving === "review_tag_visible"}
                    onCheckedChange={(checked) =>
                        handleToggle(
                            "review_tag_visible",
                            checked,
                            t(
                                "build.tagConsole.reviewTagFeatureOffConfirm",
                                "关闭后，AI 打标将不再产生新的待审核标签。已提交的待审核标签仍可在此处理。确认关闭？",
                            ),
                        )
                    }
                />
            </label>
        </div>
    )
}
