import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    addTagBlacklistApi,
    deleteTagBlacklistApi,
    searchTagBlacklistApi,
    type TagBlacklistItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Trash2 } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
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

    const load = useCallback(
        async (targetPage: number) => {
            setLoading(true)
            const res = await captureAndAlertRequestErrorHoc(
                searchTagBlacklistApi({
                    keyword: appliedKeyword.trim() || undefined,
                    page: targetPage,
                    page_size: pageSize,
                }),
            )
            setRows(res?.data || [])
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
        setAppliedKeyword(keyword)
    }

    const handleOpenAdd = () => {
        if (count >= limit) {
            toast({
                variant: "error",
                description: t("build.tagConsole.blacklistLimitReached", "黑名单已达 {{limit}} 条上限", { limit }),
            })
            return
        }
        setAddOpen(true)
    }

    const handleAdd = async (name: string) => {
        setSaving(true)
        const res = await captureAndAlertRequestErrorHoc(addTagBlacklistApi(name))
        setSaving(false)
        if (!res) return
        toast({ variant: "success", description: t("build.saved", "已保存") })
        setAddOpen(false)
        setPage(1)
        void load(1)
    }

    const handleDelete = (row: TagBlacklistItem) => {
        bsConfirm({
            title: t("build.tagConsole.blacklistRemove", "移除"),
            desc: t("build.tagConsole.blacklistDeleteConfirm", "确定从黑名单中移除该标签？"),
            showClose: true,
            okTxt: t("build.confirmDelete", "确认删除"),
            canelTxt: t("cancel", { ns: "bs" }),
            async onOk(next) {
                const res = await captureAndAlertRequestErrorHoc(deleteTagBlacklistApi(row.id))
                if (res) {
                    toast({ variant: "success", description: t("build.deleted", "已删除") })
                    void load(page)
                }
                next?.()
            },
        })
    }

    return (
        <div className="flex h-full min-w-0 flex-1 flex-col">
            <div className="flex items-center gap-3 border-b border-[#E5E6EB] bg-background px-4 py-2.5">
                <SearchInput
                    className="w-64"
                    placeholder={t("build.tagConsole.blacklistSearch", "搜索黑名单")}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                />
                <Button size="sm" onClick={handleSearch}>
                    {t("build.tagConsole.search", "搜索")}
                </Button>
                <Button size="sm" onClick={handleOpenAdd}>
                    {t("build.tagConsole.blacklistAdd", "添加")}
                </Button>
                <span className="ml-auto text-sm text-[#86909C]">
                    {t("build.tagConsole.blacklistCount", "{{count}} / {{limit}}", { count, limit })}
                </span>
            </div>

            <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full border-collapse text-sm">
                    <thead className="sticky top-0 z-10 bg-[#F7F8FA]">
                        <tr className="border-b border-[#E5E6EB] text-left text-xs uppercase tracking-wide text-[#86909C]">
                            <th className="w-14 px-3 py-3 font-medium">{t("build.tagConsole.index", "序号")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagName", "标签名称")}</th>
                            <th className="w-48 px-3 py-3 font-medium">{t("build.tagConsole.createDate", "创建日期")}</th>
                            <th className="w-20 px-3 py-3 font-medium">{t("build.tagConsole.handle", "处理")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan={4} className="px-3 py-10 text-center text-muted-foreground">
                                    {t("loading")}
                                </td>
                            </tr>
                        ) : !rows.length ? (
                            <tr>
                                <td colSpan={4} className="px-3 py-10 text-center text-muted-foreground">
                                    {t("build.tagConsole.blacklistEmpty", "暂无黑名单标签")}
                                </td>
                            </tr>
                        ) : (
                            rows.map((row, index) => (
                                <tr key={row.id} className="border-b border-[#F2F3F5]">
                                    <td className="px-3 py-3 text-[#86909C]">{(page - 1) * pageSize + index + 1}</td>
                                    <td className="px-3 py-3">{row.name}</td>
                                    <td className="px-3 py-3 text-[#86909C]">{formatDateTime(row.create_time)}</td>
                                    <td className="px-3 py-3">
                                        <button type="button" onClick={() => handleDelete(row)}>
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

            <AddBlacklistDialog
                open={addOpen}
                saving={saving}
                onOpenChange={setAddOpen}
                onConfirm={handleAdd}
            />
        </div>
    )
}
