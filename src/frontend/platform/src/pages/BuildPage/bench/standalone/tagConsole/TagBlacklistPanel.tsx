import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { SearchInput } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    addTagBlacklistApi,
    deleteTagBlacklistApi,
    previewTagBlacklistApi,
    searchTagBlacklistApi,
    type TagBlacklistItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Trash2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { AddBlacklistDialog } from "./AddBlacklistDialog"
import { formatDateTime } from "./tagConsoleTypes"

const DEFAULT_PAGE_SIZE = 20
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

export function TagBlacklistPanel() {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [keyword, setKeyword] = useState("")
    const [appliedKeyword, setAppliedKeyword] = useState("")
    const [rows, setRows] = useState<TagBlacklistItem[]>([])
    const [total, setTotal] = useState(0)
    const [count, setCount] = useState(0)
    const [limit, setLimit] = useState(1000)
    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
    const [loading, setLoading] = useState(false)
    const [addOpen, setAddOpen] = useState(false)
    const [saving, setSaving] = useState(false)
    const [selectedIds, setSelectedIds] = useState<number[]>([])
    const [deleting, setDeleting] = useState(false)
    const loadVersion = useRef(0)
    const busy = saving || deleting
    const allChecked = rows.length > 0 && rows.every((row) => selectedIds.includes(row.id))

    const load = useCallback(
        async (targetPage: number, preserveSelection = false) => {
            const version = ++loadVersion.current
            setLoading(true)
            if (!preserveSelection) setSelectedIds([])
            const res = await captureAndAlertRequestErrorHoc(
                searchTagBlacklistApi({
                    keyword: appliedKeyword.trim() || undefined,
                    page: targetPage,
                    page_size: pageSize,
                }),
            )
            if (version !== loadVersion.current) return
            if (preserveSelection && (!res || res === "canceled")) {
                setLoading(false)
                return
            }
            setRows(res?.data || [])
            setSelectedIds((ids) => ids.filter((id) => res?.data?.some((row) => row.id === id)))
            setTotal(res?.total || 0)
            setCount(res?.count || 0)
            setLimit(res?.limit || 1000)
            setLoading(false)
        },
        [appliedKeyword, pageSize],
    )

    useEffect(() => {
        setPage(1)
        void load(1)
    }, [load])

    const handleSearch = () => {
        if (busy) return
        setAppliedKeyword(keyword)
    }

    const handleOpenAdd = () => {
        if (busy) return
        if (count >= limit) {
            toast({
                variant: "error",
                description: t("build.tagConsole.blacklistLimitReached", "黑名单已达 {{limit}} 条上限", { limit }),
            })
            return
        }
        setAddOpen(true)
    }

    const handleAdd = async (names: string[]): Promise<string[]> => {
        setSaving(true)
        let savedCount = 0
        try {
            const preview = await captureAndAlertRequestErrorHoc(previewTagBlacklistApi(names))
            if (!preview || preview === "canceled") return names
            if (preview.would_exceed) {
                toast({
                    variant: "error",
                    description: t("build.tagConsole.blacklistBatchLimitExceeded", "本次添加将超过 {{limit}} 条上限，请减少标签数量。", { limit: preview.limit }),
                })
                return names
            }
            for (const name of names) {
                const res = await captureAndAlertRequestErrorHoc(addTagBlacklistApi(name))
                if (!res || res === "canceled") {
                    if (savedCount) {
                        toast({
                            variant: "error",
                            description: t("build.tagConsole.blacklistPartialSaved", "已添加 {{count}} 条，未完成的标签已保留，请检查后重试。", { count: savedCount }),
                        })
                    }
                    return names.slice(savedCount)
                }
                savedCount += 1
            }
            toast({ variant: "success", description: t("build.saved", "已保存") })
            setAddOpen(false)
            return []
        } finally {
            setSaving(false)
            if (savedCount) {
                setPage(1)
                void load(1)
            }
        }
    }

    const handleDelete = (ids: number[], batch = false) => {
        if (busy || loading || !ids.length) return
        setDeleting(true)
        bsConfirm({
            title: batch ? t("build.tagConsole.batchDelete", "批量删除") : t("build.tagConsole.blacklistRemove", "移除"),
            desc: batch
                ? t("build.tagConsole.blacklistBatchDeleteConfirm", "确定从黑名单中移除选中的 {{count}} 个标签？", { count: ids.length })
                : t("build.tagConsole.blacklistDeleteConfirm", "确定从黑名单中移除该标签？"),
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            onClose: () => setDeleting(false),
            async onOk(next) {
                const deletedIds: number[] = []
                try {
                    for (const id of ids) {
                        const res = await captureAndAlertRequestErrorHoc(deleteTagBlacklistApi(id))
                        if (res !== true) break
                        deletedIds.push(id)
                    }
                    const remaining = ids.length - deletedIds.length
                    toast({
                        variant: remaining ? "error" : "success",
                        description: remaining
                            ? t("build.tagConsole.blacklistPartialDeleted", "已删除 {{count}} 条，剩余 {{remaining}} 条未完成，请重试。", { count: deletedIds.length, remaining })
                            : t("build.deleted", "已删除"),
                    })
                    if (deletedIds.length) {
                        setRows((current) => current.filter((row) => !deletedIds.includes(row.id)))
                        setTotal((current) => Math.max(0, current - deletedIds.length))
                        setCount((current) => Math.max(0, current - deletedIds.length))
                        setSelectedIds((current) => current.filter((id) => !deletedIds.includes(id)))
                        const targetPage = Math.min(page, Math.max(1, Math.ceil((total - deletedIds.length) / pageSize)))
                        setPage(targetPage)
                        await load(targetPage, true)
                    }
                } finally {
                    setDeleting(false)
                    next?.()
                }
            },
        })
    }

    return (
        <div className="flex h-full min-w-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E6EB] bg-background px-4 py-2.5">
                <SearchInput
                    disabled={busy}
                    className="w-64"
                    placeholder={t("build.tagConsole.blacklistSearch", "搜索黑名单")}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                />
                <Button size="sm" disabled={busy} onClick={handleSearch}>
                    {t("build.tagConsole.search", "搜索")}
                </Button>
                <Button size="sm" disabled={busy} onClick={handleOpenAdd}>
                    {t("build.tagConsole.blacklistAdd", "添加")}
                </Button>
                <Button size="sm" variant="outline" disabled={busy || loading || !selectedIds.length} onClick={() => handleDelete([...selectedIds], true)}>
                    {t("build.tagConsole.batchDelete", "批量删除")}
                </Button>
                {selectedIds.length > 0 && (
                    <span className="text-sm text-muted-foreground">
                        {t("build.tagConsole.blacklistSelectedCount", "已选择 {{count}} 项", { count: selectedIds.length })}
                    </span>
                )}
                <span className="ml-auto text-sm text-[#86909C]">
                    {t("build.tagConsole.blacklistCount", "{{count}} / {{limit}}", { count, limit })}
                </span>
            </div>

            <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full border-collapse text-sm">
                    <thead className="sticky top-0 z-10 bg-[#F7F8FA]">
                        <tr className="border-b border-[#E5E6EB] text-left text-xs uppercase tracking-wide text-[#86909C]">
                            <th className="w-10 px-3 py-3">
                                <Checkbox
                                    aria-label={t("build.tagConsole.blacklistSelectPage", "全选当前页")}
                                    disabled={busy || loading || !rows.length}
                                    checked={allChecked ? true : selectedIds.length ? "indeterminate" : false}
                                    onCheckedChange={(checked) => setSelectedIds(checked === true ? rows.map((row) => row.id) : [])}
                                />
                            </th>
                            <th className="w-14 px-3 py-3 font-medium">{t("build.tagConsole.index", "序号")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagName", "标签名称")}</th>
                            <th className="w-48 px-3 py-3 font-medium">{t("build.tagConsole.createDate", "创建日期")}</th>
                            <th className="w-20 px-3 py-3 font-medium">{t("build.tagConsole.handle", "处理")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan={5} className="px-3 py-10 text-center text-muted-foreground">
                                    {t("loading")}
                                </td>
                            </tr>
                        ) : !rows.length ? (
                            <tr>
                                <td colSpan={5} className="px-3 py-10 text-center text-muted-foreground">
                                    {t("build.tagConsole.blacklistEmpty", "暂无黑名单标签")}
                                </td>
                            </tr>
                        ) : (
                            rows.map((row, index) => (
                                <tr key={row.id} className="border-b border-[#F2F3F5]">
                                    <td className="px-3 py-3">
                                        <Checkbox
                                            aria-label={t("build.tagConsole.blacklistSelectTag", "选择 {{name}}", { name: row.name })}
                                            disabled={busy}
                                            checked={selectedIds.includes(row.id)}
                                            onCheckedChange={(checked) => setSelectedIds((current) => checked === true ? [...current, row.id] : current.filter((id) => id !== row.id))}
                                        />
                                    </td>
                                    <td className="px-3 py-3 text-[#86909C]">{(page - 1) * pageSize + index + 1}</td>
                                    <td className="px-3 py-3">{row.name}</td>
                                    <td className="px-3 py-3 text-[#86909C]">{formatDateTime(row.create_time)}</td>
                                    <td className="px-3 py-3">
                                        <button type="button" disabled={busy} aria-label={t("build.tagConsole.blacklistRemove", "移除")} onClick={() => handleDelete([row.id])}>
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
                    onPageSizeChange={(value) => { if (!busy) setPageSize(value) }}
                    onChange={(value) => {
                        if (busy) return
                        setPage(value)
                        void load(value)
                    }}
                />
            </div>

            <AddBlacklistDialog
                open={addOpen}
                saving={saving}
                onOpenChange={setAddOpen}
                onConfirm={handleAdd}
            />
        </div>
    )
}
