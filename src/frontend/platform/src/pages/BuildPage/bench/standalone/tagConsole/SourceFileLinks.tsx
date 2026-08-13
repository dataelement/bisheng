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
    const { t } = useTranslation()
    const [violation, setViolation] = useState<string | null>(null)

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
                            onClick={() => setViolation(sensitiveViolationMessage(file.remark, t))}
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
            <ViolationDialog message={violation} onClose={() => setViolation(null)} />
        </div>
    )
}
