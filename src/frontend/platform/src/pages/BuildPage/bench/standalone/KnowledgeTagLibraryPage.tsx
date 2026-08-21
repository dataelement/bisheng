// Standalone tag management console (F079).
// Mounted at /standalone/knowledge-tag-library without the platform shell.
//
// Left panel picks the data source; the right panel switches between two
// independent listings rather than filtering one merged table:
//   - library mode: approved tags
//   - review mode:  pending / rejected tags, with a "handle" action per row
import {
    getTagConsolePendingCountApi,
    type KnowledgeSpaceTagLibraryListItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { ReviewTablePanel } from "./tagConsole/ReviewTablePanel"
import { TagFeatureToggles } from "./tagConsole/TagFeatureToggles"
import { TagLibraryPanel } from "./tagConsole/TagLibraryPanel"
import { TagTablePanel } from "./tagConsole/TagTablePanel"
import {
    INITIAL_SELECTION,
    selectLibrary,
    selectReviewEntry,
    type TagConsoleSelection,
} from "./tagConsole/tagConsoleTypes"

export default function KnowledgeTagLibraryPage() {
    const { t } = useTranslation()
    const [selection, setSelection] = useState<TagConsoleSelection>(INITIAL_SELECTION)
    const [libraries, setLibraries] = useState<KnowledgeSpaceTagLibraryListItem[]>([])
    const [pendingCount, setPendingCount] = useState(0)
    const [libraryRefreshToken, setLibraryRefreshToken] = useState(0)

    const refreshPendingCount = useCallback(async () => {
        const res = await captureAndAlertRequestErrorHoc(getTagConsolePendingCountApi())
        setPendingCount(res?.pending_count ?? 0)
    }, [])

    useEffect(() => {
        void refreshPendingCount()
    }, [refreshPendingCount])

    /**
     * Anything that writes tags changes a library's tag count, and approving
     * also changes the pending badge — so both sides of the page have to be
     * pulled again, not just the badge.
     */
    const handleTagsChanged = useCallback(() => {
        void refreshPendingCount()
        setLibraryRefreshToken((token) => token + 1)
    }, [refreshPendingCount])

    const handleLibrariesChanged = useCallback((rows: KnowledgeSpaceTagLibraryListItem[]) => {
        setLibraries(rows)
        // Drop selections whose library another admin deleted meanwhile.
        setSelection((prev) => {
            const existing = new Set(rows.map((row) => row.id))
            const kept = prev.selectedLibraryIds.filter((id) => existing.has(id))
            return kept.length === prev.selectedLibraryIds.length ? prev : { ...prev, selectedLibraryIds: kept }
        })
    }, [])

    return (
        <div className="flex h-full flex-col bg-[#F5F6F8] p-3">
            <div className="mb-3 flex items-center gap-3 px-1">
                <h1 className="shrink-0 text-base font-semibold">
                    {t("build.tagLibraryManagementTitle", "标签管理")}
                </h1>
                <p className="truncate text-xs text-[#86909C]">
                    {t(
                        "build.tagLibraryManagementDesc",
                        "维护平台标签库；知识空间可绑定一个或多个标签库，AI 打标从库中选取候选标签。",
                    )}
                </p>
                {/* Pushed right and never shrunk: the description truncates first,
                    because a switch whose state cannot be read is worse than a
                    sentence that is cut short. */}
                <div className="ml-auto">
                    <TagFeatureToggles />
                </div>
            </div>

            <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-[#E5E6EB] bg-background shadow-sm">
                <TagLibraryPanel
                    mode={selection.mode}
                    selectedLibraryIds={selection.selectedLibraryIds}
                    pendingCount={pendingCount}
                    onSelectLibrary={(libraryId) => setSelection((prev) => selectLibrary(prev, libraryId))}
                    onSelectReviewEntry={() => setSelection(selectReviewEntry())}
                    onLibrariesChanged={handleLibrariesChanged}
                    refreshToken={libraryRefreshToken}
                />

                {selection.mode === "review" ? (
                    <ReviewTablePanel libraries={libraries} onReviewed={handleTagsChanged} />
                ) : (
                    <TagTablePanel
                        selectedLibraryIds={selection.selectedLibraryIds}
                        libraries={libraries}
                        onLibraryContentChanged={handleTagsChanged}
                    />
                )}
            </div>
        </div>
    )
}
