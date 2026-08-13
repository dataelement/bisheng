import type { TagConsoleSourceFile } from "@/controllers/API/knowledgeSpaceTagLibrary"
import { isViolationFile, sensitiveViolationMessage } from "@/util/sensitiveViolation"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { buildTagFileDetailUrl } from "./tagConsoleTypes"
import { ViolationDialog } from "./ViolationDialog"

/**
 * Source knowledge files, each opening the portal preview in a new tab.
 *
 * A file that failed the content-safety check is deliberately not previewable:
 * clicking it explains why instead of opening it, so the offending content is
 * never rendered. The wording is the one the knowledge file list already uses.
 *
 * A file missing any part needed for the deep link degrades to plain text
 * rather than rendering a link that would land on a broken page.
 */
export function SourceFileLinks({ files, max = 3 }: { files: TagConsoleSourceFile[]; max?: number }) {
    // The violation wording lives in the knowledge namespace, which this page
    // does not otherwise use. i18next only fetches namespaces that are declared
    // or asked for by name — without this the keys never load at all and render
    // raw. Listing "bs" first keeps it the default for every other key here.
    const { t } = useTranslation(["bs", "knowledge"])
    // The file, not the finished sentence: holding the string would freeze
    // whatever the translation returned at click time, so a namespace that
    // finished loading a moment later could never correct it.
    const [violating, setViolating] = useState<TagConsoleSourceFile | null>(null)

    if (!files?.length) return <span className="text-muted-foreground">-</span>

    const shown = files.slice(0, max)
    const rest = files.length - shown.length

    return (
        <div className="flex flex-col gap-0.5">
            {shown.map((file) => {
                if (isViolationFile(file)) {
                    return (
                        <button
                            key={file.file_id}
                            type="button"
                            className="truncate text-left text-[#F53F3F] hover:underline"
                            title={t("build.tagConsole.violationBlocked", "该文件包含违规内容，无法预览")}
                            onClick={() => setViolating(file)}
                        >
                            {file.file_name}
                        </button>
                    )
                }
                const url = buildTagFileDetailUrl(file)
                if (!url) {
                    return (
                        <span key={file.file_id} className="truncate">
                            {file.file_name}
                        </span>
                    )
                }
                return (
                    <a
                        key={file.file_id}
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="truncate text-blue-600 hover:underline"
                    >
                        {file.file_name}
                    </a>
                )
            })}
            {rest > 0 && (
                <span className="text-xs text-muted-foreground">
                    {t("build.tagConsole.moreFiles", "等 {{count}} 个文件", { count: files.length })}
                </span>
            )}
            <ViolationDialog
                message={violating ? sensitiveViolationMessage(violating.remark, t) : null}
                onClose={() => setViolating(null)}
            />
        </div>
    )
}
