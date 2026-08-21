import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    batchDeleteTagConsoleApi,
    batchMoveTagConsoleApi,
    createTagConsoleTagApi,
    searchTagConsoleApi,
    type KnowledgeSpaceTagLibraryListItem,
    type TagConsoleBatchResult,
    type TagConsoleItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { AddTagDialog } from "./AddTagDialog"
import { SourceFileLinks } from "./SourceFileLinks"
import { BatchResultDialog, LibraryPickerDialog } from "./TagBatchDialogs"
import { TagFilterBar } from "./TagFilterBar"
import { TagSourceIcon, tagSourceLabel } from "./TagSourceIcon"
import {
    buildSearchParams,
    EMPTY_FILTERS,
    formatDateTime,
    sourceLibraryNames,
    type TagConsoleFilterState,
} from "./tagConsoleTypes"

const DEFAULT_PAGE_SIZE = 20
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

interface TagTablePanelProps {
    selectedLibraryIds: number[]
    libraries: KnowledgeSpaceTagLibraryListItem[]
    onLibraryContentChanged: () => void
}

export function TagTablePanel({ selectedLibraryIds, libraries, onLibraryContentChanged }: TagTablePanelProps) {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [filters, setFilters] = useState<TagConsoleFilterState>(EMPTY_FILTERS)
    const [appliedFilters, setAppliedFilters] = useState<TagConsoleFilterState>(EMPTY_FILTERS)
    const [rows, setRows] = useState<TagConsoleItem[]>([])
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
    const [loading, setLoading] = useState(false)
    const [selectedIds, setSelectedIds] = useState<number[]>([])
    const [addOpen, setAddOpen] = useState(false)
    const [moveOpen, setMoveOpen] = useState(false)
    const [saving, setSaving] = useState(false)
    const [batchResult, setBatchResult] = useState<TagConsoleBatchResult | null>(null)

    const load = useCallback(
        async (targetPage: number) => {
            setLoading(true)
            const res = await captureAndAlertRequestErrorHoc(
                searchTagConsoleApi({
                    ...buildSearchParams(appliedFilters, targetPage, pageSize),
                    library_ids: selectedLibraryIds,
                }),
            )
            setRows(res?.data || [])
            setTotal(res?.total || 0)
            setSelectedIds([])
            setLoading(false)
        },
        // pageSize is a dependency on purpose: changing it rebuilds `load`,
        // which the effect below turns into a reset to page 1 plus a reload.
        // That is what keeps a size change from leaving the view on a page
        // that no longer exists.
        [appliedFilters, selectedLibraryIds, pageSize],
    )

    useEffect(() => {
        setPage(1)
        void load(1)
    }, [load])

    const refresh = () => {
        void load(page)
        onLibraryContentChanged()
    }

    const finishBatch = (result: TagConsoleBatchResult | null) => {
        setSaving(false)
        if (!result) return
        setBatchResult(result)
        refresh()
    }

    const handleAdd = async (tagName: string, libraryId: number) => {
        setSaving(true)
        const res = await captureAndAlertRequestErrorHoc(createTagConsoleTagApi({ tag_name: tagName, library_id: libraryId }))
        setSaving(false)
        if (!res) return
        toast({ variant: "success", description: t("build.saved", "已保存") })
        setAddOpen(false)
        refresh()
    }

    const handleDelete = (ids: number[]) => {
        bsConfirm({
            title: t("build.deleteTagTitle", "删除标签"),
            desc: t("build.tagConsole.deleteConfirm", "确定删除选中的标签？删除后其与知识文件的关联也会一并移除。"),
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            async onOk(next) {
                setSaving(true)
                finishBatch(await captureAndAlertRequestErrorHoc(batchDeleteTagConsoleApi(ids)))
                next?.()
            },
        })
    }

    const handleMove = async (targetLibraryId: number) => {
        setSaving(true)
        setMoveOpen(false)
        finishBatch(await captureAndAlertRequestErrorHoc(batchMoveTagConsoleApi(selectedIds, targetLibraryId)))
    }

    const allChecked = rows.length > 0 && selectedIds.length === rows.length

    return (
        <div className="flex h-full min-w-0 flex-1 flex-col">
            <TagFilterBar
                filters={filters}
                showStatus={false}
                onChange={setFilters}
                onSearch={() => setAppliedFilters(filters)}
                onReset={() => {
                    // A fresh object on purpose: reloading is keyed on the
                    // applied filters by reference, so reusing the constant
                    // would make a reset on an untouched form do nothing.
                    setFilters({ ...EMPTY_FILTERS })
                    setAppliedFilters({ ...EMPTY_FILTERS })
                }}
            />

            <div className="flex flex-wrap items-center gap-2 border-b border-[#E5E6EB] bg-background px-4 py-2.5">
                <span className="mr-auto text-sm font-medium">
                    {t("build.tagConsole.tagListTitle", "标签列表")}
                    <span className="ml-2 text-muted-foreground">({total})</span>
                </span>
                <Button size="sm" onClick={() => setAddOpen(true)}>
                    {t("build.addTag", "添加")}
                </Button>
                <Button
                    size="sm"
                    variant="outline"
                    disabled={!selectedIds.length}
                    onClick={() => handleDelete(selectedIds)}
                >
                    {t("build.tagConsole.batchDelete", "批量删除")}
                </Button>
                <Button size="sm" variant="outline" disabled={!selectedIds.length} onClick={() => setMoveOpen(true)}>
                    {t("build.tagConsole.batchMove", "批量移动")}
                </Button>
            </div>

            <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full min-w-[1200px] border-collapse text-sm">
                    <thead className="sticky top-0 z-10 bg-[#F7F8FA]">
                        <tr className="border-b border-[#E5E6EB] text-left text-xs uppercase tracking-wide text-[#86909C]">
                            <th className="w-10 px-3 py-3">
                                <Checkbox
                                    checked={allChecked}
                                    onCheckedChange={(checked) =>
                                        setSelectedIds(checked ? rows.map((row) => row.id) : [])
                                    }
                                />
                            </th>
                            <th className="w-14 px-3 py-3 font-medium">{t("build.tagConsole.index", "序号")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.libraryName", "标签库名")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagName", "标签名称")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.markedCount", "已标识知识数")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.submitter", "提报者")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.reviewer", "审核者")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.tagType", "标签类型")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.sourceLibrary", "标签来源库")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.sourceKnowledge", "标签来源知识")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.createDate", "创建日期")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.reviewTime", "审核时间")}</th>
                            <th className="w-16 px-3 py-3 font-medium">{t("build.operation", "操作")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan={13} className="px-3 py-10 text-center text-muted-foreground">
                                    {t("loading")}
                                </td>
                            </tr>
                        ) : !rows.length ? (
                            <tr>
                                <td colSpan={13} className="px-3 py-10 text-center text-muted-foreground">
                                    {t("build.tagConsole.empty", "暂无标签")}
                                </td>
                            </tr>
                        ) : (
                            rows.map((row, index) => (
                                <tr key={row.id} className="border-b border-[#F2F3F5] hover:bg-[#F7F8FA]">
                                    <td className="px-3 py-3">
                                        <Checkbox
                                            checked={selectedIds.includes(row.id)}
                                            onCheckedChange={(checked) =>
                                                setSelectedIds((prev) =>
                                                    checked ? [...prev, row.id] : prev.filter((id) => id !== row.id),
                                                )
                                            }
                                        />
                                    </td>
                                    <td className="px-3 py-3 text-muted-foreground">
                                        {(page - 1) * pageSize + index + 1}
                                    </td>
                                    <td className="px-3 py-3">{row.library_name || "-"}</td>
                                    <td className="px-3 py-3 font-medium">
                                        <TagSourceIcon resourceType={row.resource_type} />
                                        {row.name}
                                    </td>
                                    <td className="px-3 py-3">{row.marked_knowledge_count}</td>
                                    <td className="px-3 py-3">{row.submitter_name || "-"}</td>
                                    <td className="px-3 py-3">{row.reviewer_name || "-"}</td>
                                    <td className="px-3 py-3">{tagSourceLabel(row.resource_type, t)}</td>
                                    <td className="max-w-48 px-3 py-3">
                                        {sourceLibraryNames(row.source_files).join("、") || "-"}
                                    </td>
                                    <td className="max-w-64 px-3 py-3">
                                        <SourceFileLinks files={row.source_files} />
                                    </td>
                                    <td className="px-3 py-3 text-muted-foreground">{formatDateTime(row.create_time)}</td>
                                    <td className="px-3 py-3 text-muted-foreground">{formatDateTime(row.review_time)}</td>
                                    <td className="px-3 py-3">
                                        <button type="button" onClick={() => handleDelete([row.id])}>
                                            <Trash2 className="size-4 text-muted-foreground hover:text-red-500" />
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            <div className="flex justify-end border-t border-[#E5E6EB] bg-background px-4 py-2">
                <AutoPagination
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    showJumpInput
                    jumpToText={t("pagination.jumpTo", "跳至")}
                    pageText={t("pagination.pageUnit", "页")}
                    pageSizeOptions={PAGE_SIZE_OPTIONS}
                    onPageSizeChange={setPageSize}
                    onChange={(value) => {
                        setPage(value)
                        void load(value)
                    }}
                />
            </div>

            <AddTagDialog
                open={addOpen}
                saving={saving}
                libraries={libraries}
                defaultLibraryId={selectedLibraryIds.length === 1 ? selectedLibraryIds[0] : null}
                onOpenChange={setAddOpen}
                onConfirm={handleAdd}
            />
            <LibraryPickerDialog
                open={moveOpen}
                title={t("build.tagConsole.batchMove", "批量移动")}
                libraries={libraries}
                saving={saving}
                onOpenChange={setMoveOpen}
                onConfirm={handleMove}
            />
            <BatchResultDialog result={batchResult} onOpenChange={() => setBatchResult(null)} />
        </div>
    )
}
