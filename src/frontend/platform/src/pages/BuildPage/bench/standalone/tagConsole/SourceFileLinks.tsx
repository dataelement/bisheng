import type { TagConsoleSourceFile } from "@/controllers/API/knowledgeSpaceTagLibrary"
import { useTranslation } from "react-i18next"
import { buildTagFileDetailUrl } from "./tagConsoleTypes"

/**
 * Source knowledge files, each opening the portal preview in a new tab.
 *
 * A file missing any part needed for the deep link degrades to plain text
 * rather than rendering a link that would land on a broken page.
 */
export function SourceFileLinks({ files, max = 3 }: { files: TagConsoleSourceFile[]; max?: number }) {
    const { t } = useTranslation()

    if (!files?.length) return <span className="text-muted-foreground">-</span>

    const shown = files.slice(0, max)
    const rest = files.length - shown.length

    return (
        <div className="flex flex-col gap-0.5">
            {shown.map((file) => {
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
        </div>
    )
}
