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
    reorderKnowledgeSpaceTagLibraryApi,
    type KnowledgeSpaceTagLibraryDetail,
    type KnowledgeSpaceTagLibraryListItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { cname } from "@/components/bs-ui/utils"
import { Ban, ClipboardCheck, GripVertical, Pencil, Plus, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { DragDropContext, Draggable, Droppable, type DropResult } from "react-beautiful-dnd"
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
    onSelectBlacklistEntry: () => void
    /** Bubbles up so the right panel can drop a library that no longer exists. */
    onLibrariesChanged: (libraries: KnowledgeSpaceTagLibraryListItem[]) => void
    /**
     * Bumped by the right panel whenever it writes tags.
     *
     * The tag counts shown here are computed server-side, so adding, deleting
     * or moving a tag makes them stale immediately — without this the panel
     * kept its mount-time numbers until the page was reloaded.
     */
    refreshToken: number
}

export function TagLibraryPanel({
    mode,
    selectedLibraryIds,
    pendingCount,
    onSelectLibrary,
    onSelectReviewEntry,
    onSelectBlacklistEntry,
    onLibrariesChanged,
    refreshToken,
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
    }, [loadLibraries, refreshToken])

    // Filtering is client-side so the fixed "pending review" entry never
    // disappears while the user searches for a library.
    const visibleLibraries = libraries.filter((library) =>
        library.name.toLowerCase().includes(keyword.trim().toLowerCase()),
    )

    // Dragging a filtered list would be a lie: the row above the drop point on
    // screen is not the row above it in the real order, so the neighbours we
    // send would place the library somewhere the user did not aim for.
    const isFiltering = keyword.trim().length > 0

    // Synchronous by contract: the library reorders the list from what this
    // returns, so the request is fired detached rather than awaited here.
    const handleDragEnd = (result: DropResult) => {
        const { source, destination } = result
        if (!destination || destination.index === source.index) return

        const next = [...libraries]
        const [moved] = next.splice(source.index, 1)
        if (!moved) return
        next.splice(destination.index, 0, moved)

        // Optimistic: the list settles under the cursor instead of snapping back
        // for the length of a round trip.
        const previous = libraries
        setLibraries(next)
        onLibrariesChanged(next)

        void (async () => {
            const res = await captureAndAlertRequestErrorHoc(
                reorderKnowledgeSpaceTagLibraryApi(moved.id, {
                    prev_library_id: next[destination.index - 1]?.id ?? null,
                    next_library_id: next[destination.index + 1]?.id ?? null,
                }),
            )
            if (!res) {
                setLibraries(previous)
                onLibrariesChanged(previous)
            }
        })()
    }

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

            <button
                type="button"
                onClick={onSelectBlacklistEntry}
                className={cname(
                    "flex items-center justify-between border-l-[3px] border-b border-b-[#E5E6EB] px-4 py-3 text-left text-sm transition-colors",
                    mode === "blacklist"
                        ? "border-l-primary bg-primary/10 font-medium text-primary"
                        : "border-l-transparent hover:bg-[#F2F3F5]",
                )}
            >
                <span className="flex items-center gap-2">
                    <Ban className="size-4" />
                    {t("build.tagConsole.blacklistEntry", "标签黑名单")}
                </span>
            </button>

            <div className="flex-1 overflow-y-auto">
                {loading ? (
                    <p className="px-4 py-6 text-center text-sm text-muted-foreground">{t("loading")}</p>
                ) : !visibleLibraries.length ? (
                    <p className="px-4 py-6 text-center text-sm text-muted-foreground">
                        {t("build.tagConsole.noLibrary", "暂无标签库")}
                    </p>
                ) : (
                    <TooltipProvider delayDuration={200}>
                    <DragDropContext onDragEnd={handleDragEnd}>
                        <Droppable droppableId="tagLibraries">
                            {(droppable) => (
                                <div ref={droppable.innerRef} {...droppable.droppableProps}>
                                    {visibleLibraries.map((library, index) => {
                                        const selected =
                                            mode === "library" && selectedLibraryIds.includes(library.id)
                                        return (
                                            <Draggable
                                                key={library.id}
                                                draggableId={String(library.id)}
                                                index={index}
                                                isDragDisabled={isFiltering}
                                            >
                                                {(draggable, snapshot) => (
                                                    <div
                                                        ref={draggable.innerRef}
                                                        {...draggable.draggableProps}
                                                        onClick={() => {
                                                            if (snapshot.isDragging) return
                                                            onSelectLibrary(library.id)
                                                        }}
                                                        className={cname(
                                                            "group flex cursor-pointer items-center justify-between border-l-[3px] px-4 py-2.5 text-sm",
                                                            // The library animates transform on drop and watches for that
                                                            // transition to end. A transition of our own on the same
                                                            // element is one more thing that can fire first.
                                                            !snapshot.isDragging && "transition-colors",
                                                            selected
                                                                ? "border-l-primary bg-primary/10 font-medium text-primary"
                                                                : "border-l-transparent hover:bg-[#F2F3F5]",
                                                            snapshot.isDragging && "bg-background shadow-md",
                                                        )}
                                                    >
                                                        {/* Handle only, so a plain click still selects the library. */}
                                                        <span
                                                            {...draggable.dragHandleProps}
                                                            className={cname(
                                                                "-ml-2 mr-1 shrink-0 cursor-grab text-muted-foreground",
                                                                isFiltering
                                                                    ? "invisible"
                                                                    : "opacity-0 group-hover:opacity-100",
                                                            )}
                                                            onClick={(e) => e.stopPropagation()}
                                                        >
                                                            <GripVertical className="size-3.5" />
                                                        </span>
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
                                                                        : t(
                                                                              "build.tagConsole.noBoundSpace",
                                                                              "暂无关联知识空间",
                                                                          )}
                                                                </p>
                                                            </TooltipContent>
                                                        </Tooltip>
                                                        <span className="ml-2 hidden shrink-0 items-center gap-1 group-hover:flex">
                                                            <button
                                                                type="button"
                                                                onClick={(e) => handleEdit(e, library)}
                                                            >
                                                                <Pencil className="size-3.5 text-muted-foreground hover:text-primary" />
                                                            </button>
                                                            <button
                                                                type="button"
                                                                onClick={(e) => handleDelete(e, library)}
                                                            >
                                                                <Trash2 className="size-3.5 text-muted-foreground hover:text-red-500" />
                                                            </button>
                                                        </span>
                                                    </div>
                                                )}
                                            </Draggable>
                                        )
                                    })}
                                    {droppable.placeholder}
                                </div>
                            )}
                        </Droppable>
                    </DragDropContext>
                    </TooltipProvider>
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
