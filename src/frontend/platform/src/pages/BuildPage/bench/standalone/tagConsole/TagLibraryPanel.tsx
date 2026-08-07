import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    deleteKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibrariesApi,
    getKnowledgeSpaceTagLibraryApi,
    getKnowledgeSpaceTagLibraryUsageApi,
    type KnowledgeSpaceTagLibraryDetail,
    type KnowledgeSpaceTagLibraryListItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { cname } from "@/components/bs-ui/utils"
import { ClipboardCheck, Pencil, Plus, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { TagLibraryFormDialog } from "./TagLibraryFormDialog"
import type { TagConsoleMode } from "./tagConsoleTypes"

const LIBRARY_PAGE_SIZE = 500

interface TagLibraryPanelProps {
    mode: TagConsoleMode
    selectedLibraryIds: number[]
    pendingCount: number
    onSelectLibrary: (libraryId: number) => void
    onSelectReviewEntry: () => void
    /** Bubbles up so the right panel can drop a library that no longer exists. */
    onLibrariesChanged: (libraries: KnowledgeSpaceTagLibraryListItem[]) => void
}

export function TagLibraryPanel({
    mode,
    selectedLibraryIds,
    pendingCount,
    onSelectLibrary,
    onSelectReviewEntry,
    onLibrariesChanged,
}: TagLibraryPanelProps) {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [keyword, setKeyword] = useState("")
    const [libraries, setLibraries] = useState<KnowledgeSpaceTagLibraryListItem[]>([])
    const [loading, setLoading] = useState(false)
    const [formOpen, setFormOpen] = useState(false)
    const [formMode, setFormMode] = useState<"create" | "edit">("create")
    const [editing, setEditing] = useState<KnowledgeSpaceTagLibraryDetail | null>(null)

    const loadLibraries = useCallback(async () => {
        setLoading(true)
        const res = await captureAndAlertRequestErrorHoc(
            getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: LIBRARY_PAGE_SIZE }),
        )
        const rows = res?.data || []
        setLibraries(rows)
        onLibrariesChanged(rows)
        setLoading(false)
    }, [onLibrariesChanged])

    useEffect(() => {
        void loadLibraries()
    }, [loadLibraries])

    // Filtering is client-side so the fixed "pending review" entry never
    // disappears while the user searches for a library.
    const visibleLibraries = libraries.filter((library) =>
        library.name.toLowerCase().includes(keyword.trim().toLowerCase()),
    )

    const handleCreate = () => {
        setFormMode("create")
        setEditing(null)
        setFormOpen(true)
    }

    const handleEdit = async (event: React.MouseEvent, library: KnowledgeSpaceTagLibraryListItem) => {
        event.stopPropagation()
        const detail = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryApi(library.id))
        if (!detail) return
        setFormMode("edit")
        setEditing(detail)
        setFormOpen(true)
    }

    const handleDelete = async (event: React.MouseEvent, library: KnowledgeSpaceTagLibraryListItem) => {
        event.stopPropagation()
        if (library.tag_count > 0) {
            toast({ variant: "error", description: t("build.deleteTagLibraryHasTags", "标签库中存在标签，无法删除") })
            return
        }
        const usage = await captureAndAlertRequestErrorHoc(getKnowledgeSpaceTagLibraryUsageApi(library.id))
        if ((usage?.count ?? 0) > 0) {
            toast({
                variant: "error",
                description: t("build.deleteTagLibraryHasBindings", "标签库已关联知识空间，无法删除"),
            })
            return
        }
        bsConfirm({
            title: t("build.deleteTagLibraryTitle", "删除标签库"),
            desc: t("build.deleteTagLibraryConfirm", "确定删除该空标签库吗？"),
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            async onOk(next) {
                const res = await captureAndAlertRequestErrorHoc(deleteKnowledgeSpaceTagLibraryApi(library.id))
                if (res) {
                    toast({ variant: "success", description: t("build.deleted", "已删除") })
                    void loadLibraries()
                }
                next?.()
            },
        })
    }

    return (
        <div className="flex h-full w-[260px] min-w-[260px] flex-col border-r border-[#E5E6EB] bg-[#FAFBFC]">
            <div className="flex items-center gap-2 border-b border-[#E5E6EB] p-3">
                <SearchInput
                    className="min-w-0 flex-1"
                    placeholder={t("build.tagConsole.searchLibrary", "搜索标签库名")}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                />
                <Button size="icon" className="shrink-0" onClick={handleCreate}>
                    <Plus className="size-4" />
                </Button>
            </div>

            <button
                type="button"
                onClick={onSelectReviewEntry}
                className={cname(
                    "flex items-center justify-between border-l-[3px] border-b border-b-[#E5E6EB] px-4 py-3 text-left text-sm transition-colors",
                    mode === "review"
                        ? "border-l-primary bg-primary/10 font-medium text-primary"
                        : "border-l-transparent hover:bg-[#F2F3F5]",
                )}
            >
                <span className="flex items-center gap-2">
                    <ClipboardCheck className="size-4" />
                    {t("build.tagConsole.pendingEntry", "待审核标签")}
                </span>
                {pendingCount > 0 && (
                    <span className="rounded-full bg-[#F53F3F] px-2 py-0.5 text-xs text-white">{pendingCount}</span>
                )}
            </button>

            <div className="flex-1 overflow-y-auto">
                {loading ? (
                    <p className="px-4 py-6 text-center text-sm text-muted-foreground">{t("loading")}</p>
                ) : !visibleLibraries.length ? (
                    <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                        {t("build.tagConsole.noLibrary", "暂无标签库")}
                    </p>
                ) : (
                    visibleLibraries.map((library) => {
                        const selected = mode === "library" && selectedLibraryIds.includes(library.id)
                        return (
                            <div
                                key={library.id}
                                onClick={() => onSelectLibrary(library.id)}
                                className={cname(
                                    "group flex cursor-pointer items-center justify-between border-l-[3px] px-4 py-2.5 text-sm transition-colors",
                                    selected
                                        ? "border-l-primary bg-primary/10 font-medium text-primary"
                                        : "border-l-transparent hover:bg-[#F2F3F5]",
                                )}
                            >
                                <TooltipProvider delayDuration={200}>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <span className="min-w-0 flex-1 truncate">
                                                {library.name} ({library.tag_count})
                                            </span>
                                        </TooltipTrigger>
                                        <TooltipContent side="right" className="max-w-72">
                                            <p className="whitespace-normal break-all text-left">
                                                {library.bound_space_names?.length
                                                    ? library.bound_space_names.join("、")
                                                    : t("build.tagConsole.noBoundSpace", "暂无关联知识空间")}
                                            </p>
                                        </TooltipContent>
                                    </Tooltip>
                                </TooltipProvider>
                                <span className="ml-2 hidden shrink-0 items-center gap-1 group-hover:flex">
                                    <button type="button" onClick={(e) => handleEdit(e, library)}>
                                        <Pencil className="size-3.5 text-muted-foreground hover:text-primary" />
                                    </button>
                                    <button type="button" onClick={(e) => handleDelete(e, library)}>
                                        <Trash2 className="size-3.5 text-muted-foreground hover:text-red-500" />
                                    </button>
                                </span>
                            </div>
                        )
                    })
                )}
            </div>

            <TagLibraryFormDialog
                open={formOpen}
                mode={formMode}
                initial={editing}
                onOpenChange={setFormOpen}
                onSaved={loadLibraries}
            />
        </div>
    )
}
