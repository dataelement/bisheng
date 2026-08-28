import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { previewTagBlacklistApi } from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { TFunction } from "i18next"

export type RejectBlacklistDecision = { skipBlacklist: boolean }

/**
 * Ask whether to skip writing rejected names into the blacklist when the
 * 1000-row cap would be exceeded. Cancel leaves the reject unsent.
 */
export async function confirmRejectSkipBlacklist(
    names: string[],
    t: TFunction,
): Promise<RejectBlacklistDecision | null> {
    const preview = await captureAndAlertRequestErrorHoc(previewTagBlacklistApi(names))
    if (!preview) return null
    if (!preview.would_exceed) return { skipBlacklist: false }

    return new Promise((resolve) => {
        let settled = false
        const finish = (value: RejectBlacklistDecision | null) => {
            if (settled) return
            settled = true
            resolve(value)
        }
        bsConfirm({
            title: t("build.tagConsole.blacklistLimitTitle", "黑名单将超过上限"),
            desc: t(
                "build.tagConsole.blacklistLimitConfirm",
                "黑名单当前 {{count}} 条，本次将新增 {{newCount}} 条，超过 {{limit}} 条上限。是否放弃插入黑名单并直接驳回？",
                {
                    count: preview.count,
                    newCount: preview.new_count,
                    limit: preview.limit,
                },
            ),
            showClose: true,
            okTxt: t("build.tagConsole.skipBlacklistAndReject", "放弃插入并驳回"),
            canelTxt: t("cancel", { ns: "bs" }),
            onOk(next) {
                finish({ skipBlacklist: true })
                next?.()
            },
            onCancel() {
                finish(null)
            },
            onClose() {
                finish(null)
            },
        })
    })
}
