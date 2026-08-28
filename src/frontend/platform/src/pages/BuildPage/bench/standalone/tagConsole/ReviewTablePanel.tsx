import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip"
import {
    batchApproveTagConsoleApi,
    batchRejectTagConsoleApi,
    searchTagConsoleReviewApi,
    type KnowledgeSpaceTagLibraryListItem,
    type TagConsoleBatchResult,
    type TagConsoleReviewItem,
    type TagConsoleReviewRef,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { cname } from "@/components/bs-ui/utils"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { SourceFileLinks } from "./SourceFileLinks"
import { BatchApproveLibraryPickerDialog, BatchResultDialog, RejectReasonDialog } from "./TagBatchDialogs"
import { TagFilterBar } from "./TagFilterBar"
import { TagReviewDialog } from "./TagReviewDialog"
import { TagSourceIcon } from "./TagSourceIcon"
import { confirmRejectSkipBlacklist } from "./tagBlacklistConfirm"
import {
    buildSearchParams,
    EMPTY_FILTERS,
    formatDateTime,
    reviewRequestStatus,
    reviewStatusColorClass,
    sourceLibraryNames,
    type TagConsoleFilterState,
    type TagConsoleReviewTab,
} from "./tagConsoleTypes"
import { useApprovableLibraries } from "./useApprovableLibraries"

const DEFAULT_PAGE_SIZE = 20
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

function refOf(row: TagConsoleReviewItem): TagConsoleReviewRef {
    return { name: row.name, resource_type: row.resource_type }
}

function keyOf(row: TagConsoleReviewRef): string {
    return `${row.name}\u0000${row.resource_type}`
}

interface ReviewTablePanelProps {
    libraries: KnowledgeSpaceTagLibraryListItem[]
    onReviewed: () => void
}

function TabButton({
    active,
    onClick,
    children,
}: {
    active: boolean
    onClick: () => void
    children: React.ReactNode
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cname(
                "flex items-center rounded px-3 py-1 text-sm transition-colors",
                active
                    ? "bg-background font-medium text-foreground shadow-sm"
                    : "text-[#86909C] hover:text-foreground",
            )}
        >
            {children}
        </button>
    )
}

function TabCount({ children }: { children: React.ReactNode }) {
    return <span className="ml-1.5 text-xs text-muted-foreground">({children})</span>
}

export function ReviewTablePanel({ libraries, onReviewed }: ReviewTablePanelProps) {
    const { t } = useTranslation()
    const [tab, setTab] = useState<TagConsoleReviewTab>("pending")
    const [filters, setFilters] = useState<TagConsoleFilterState>(EMPTY_FILTERS)
    const [appliedFilters, setAppliedFilters] = useState<TagConsoleFilterState>(EMPTY_FILTERS)
    const [rows, setRows] = useState<TagConsoleReviewItem[]>([])
    const [total, setTotal] = useState(0)
    const [pendingCount, setPendingCount] = useState(0)
    const [rejectedCount, setRejectedCount] = useState(0)
    const [approvedCount, setApprovedCount] = useState(0)
    const [page, setPage] = useState(1)
    const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
    const [loading, setLoading] = useState(false)
    const [selectedKeys, setSelectedKeys] = useState<string[]>([])
    const [reviewTarget, setReviewTarget] = useState<TagConsoleReviewRef | null>(null)
    const [approveOpen, setApproveOpen] = useState(false)
    const [rejectOpen, setRejectOpen] = useState(false)
    const [saving, setSaving] = useState(false)
    const [batchResult, setBatchResult] = useState<TagConsoleBatchResult | null>(null)

    const load = useCallback(
        async (targetPage: number) => {
            setLoading(true)
            const res = await captureAndAlertRequestErrorHoc(
                searchTagConsoleReviewApi({
                    ...buildSearchParams(appliedFilters, targetPage, pageSize),
                    status: reviewRequestStatus(tab, appliedFilters.status),
                }),
            )
            setRows(res?.data || [])
            setTotal(res?.total || 0)
            setPendingCount(res?.pending_count || 0)
            setRejectedCount(res?.rejected_count || 0)
            setApprovedCount(res?.approved_count || 0)
            setSelectedKeys([])
            setLoading(false)
        },
        // See TagTablePanel: pageSize belongs here so a size change resets to
        // page 1 through the same path a filter change already takes.
        [appliedFilters, tab, pageSize],
    )

    useEffect(() => {
        setPage(1)
        void load(1)
    }, [load])

    const handleTabChange = (next: TagConsoleReviewTab) => {
        if (next === tab) return
        // The status choice belongs to the reviewed tab; carrying it across
        // would leave the pending tab filtered by an outcome it cannot have.
        const cleared = { ...filters, status: "" as const }
        setFilters(cleared)
        setAppliedFilters(cleared)
        setTab(next)
    }

    const reviewedCount = approvedCount + rejectedCount
    const isPendingTab = tab === "pending"
    // Checkbox + action columns exist only where rows can still be acted on;
    // the reviewed tab shows an outcome column instead.
    const columnCount = isPendingTab ? 11 : 10

    const selectedRows = rows.filter((row) => selectedKeys.includes(keyOf(row)))
    // Already-reviewed entries are read-only, so they take part in neither action.
    const actionableRows = selectedRows.filter((row) => row.status === "pending")
    const canAct = actionableRows.length > 0

    const finishBatch = (result: TagConsoleBatchResult | null) => {
        setSaving(false)
        if (!result) return
        setBatchResult(result)
        void load(page)
        onReviewed()
    }

    const handleApprove = async (targetLibraryId: number, items: TagConsoleReviewRef[], ackSimilar = false) => {
        setSaving(true)
        setApproveOpen(false)
        setReviewTarget(null)
        finishBatch(await captureAndAlertRequestErrorHoc(batchApproveTagConsoleApi(items, targetLibraryId, ackSimilar)))
    }

    const handleReject = async (reason: string, items: TagConsoleReviewRef[]) => {
        const decision = await confirmRejectSkipBlacklist(items.map((item) => item.name), t)
        if (!decision) return
        setSaving(true)
        setRejectOpen(false)
        setReviewTarget(null)
        finishBatch(await captureAndAlertRequestErrorHoc(
            batchRejectTagConsoleApi(items, reason, decision.skipBlacklist),
        ))
    }

    const { libraries: approvableLibraries, loading: loadingLibraries } = useApprovableLibraries()

    const allChecked = rows.length > 0 && selectedKeys.length === rows.length

    return (
        <div className="flex h-full min-w-0 flex-1 flex-col">
            <TagFilterBar
                filters={filters}
                showStatus={!isPendingTab}
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
                <div className="mr-auto flex items-center gap-1 rounded-md bg-[#F2F3F5] p-0.5">
                    <TabButton active={isPendingTab} onClick={() => handleTabChange("pending")}>
                        {t("build.tagConsole.tabPending", "待审核")}
                        <TabCount>{pendingCount}</TabCount>
                    </TabButton>
                    <TabButton active={!isPendingTab} onClick={() => handleTabChange("reviewed")}>
                        {t("build.tagConsole.tabReviewed", "已审核")}
                        <TabCount>{reviewedCount}</TabCount>
                    </TabButton>
                </div>
                {isPendingTab && (
                    <>
                        <Button size="sm" disabled={!canAct} onClick={() => setApproveOpen(true)}>
                            {t("build.tagConsole.batchApprove", "批量入库")}
                        </Button>
                        <Button size="sm" variant="destructive" disabled={!canAct} onClick={() => setRejectOpen(true)}>
                            {t("build.tagConsole.batchReject", "批量驳回")}
                        </Button>
                    </>
                )}
            </div>

            <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full min-w-[1100px] border-collapse text-sm">
                    <thead className="sticky top-0 z-10 bg-[#F7F8FA]">
                        <tr className="border-b border-[#E5E6EB] text-left text-xs uppercase tracking-wide text-[#86909C]">
                            {isPendingTab && (
                                <th className="w-10 px-3 py-3">
                                    <Checkbox
                                        checked={allChecked}
                                        onCheckedChange={(checked) =>
                                            setSelectedKeys(checked ? rows.map(keyOf) : [])
                                        }
                                    />
                                </th>
                            )}
                            <th className="w-14 px-3 py-3 font-medium">{t("build.tagConsole.index", "序号")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagName", "标签名称")}</th>
                            {!isPendingTab && (
                                <th className="px-3 py-3 font-medium">{t("build.tagConsole.status", "标签状态")}</th>
                            )}
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.sourceLibrary", "标签来源库")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.sourceKnowledge", "标签来源知识")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.creator", "创建者")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.reviewer", "审核者")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.rejectReason", "驳回原因")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.createDate", "创建日期")}</th>
                            <th className="px-3 py-3 font-medium">{t("build.tagConsole.reviewTime", "审核时间")}</th>
                            {isPendingTab && (
                                <th className="w-20 px-3 py-3 font-medium">{t("build.operation", "操作")}</th>
                            )}
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan={columnCount} className="px-3 py-10 text-center text-muted-foreground">
                                    {t("loading")}
                                </td>
                            </tr>
                        ) : !rows.length ? (
                            <tr>
                                <td colSpan={columnCount} className="px-3 py-10 text-center text-muted-foreground">
                                    {isPendingTab
                                        ? t("build.tagConsole.emptyReview", "暂无待审核标签")
                                        : t("build.tagConsole.emptyReviewed", "暂无已审核标签")}
                                </td>
                            </tr>
                        ) : (
                            rows.map((row, index) => (
                                <tr key={keyOf(row)} className="border-b border-[#F2F3F5] hover:bg-[#F7F8FA]">
                                    {isPendingTab && (
                                        <td className="px-3 py-3">
                                            <Checkbox
                                                checked={selectedKeys.includes(keyOf(row))}
                                                onCheckedChange={(checked) =>
                                                    setSelectedKeys((prev) =>
                                                        checked
                                                            ? [...prev, keyOf(row)]
                                                            : prev.filter((key) => key !== keyOf(row)),
                                                    )
                                                }
                                            />
                                        </td>
                                    )}
                                    <td className="px-3 py-3 text-muted-foreground">
                                        {(page - 1) * pageSize + index + 1}
                                    </td>
                                    <td className="px-3 py-3 font-medium">
                                        <TagSourceIcon resourceType={row.resource_type} />
                                        <span className={reviewStatusColorClass(row.status)}>
                                            {row.name}
                                        </span>
                                        {row.review_tag_count > 1 && (
                                            <TooltipProvider delayDuration={200}>
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <span className="ml-1 rounded bg-[#F2F3F5] px-1.5 text-xs text-[#4E5969]">
                                                            ×{row.review_tag_count}
                                                        </span>
                                                    </TooltipTrigger>
                                                    <TooltipContent>
                                                        {t(
                                                            "build.tagConsole.multiSpaceHint",
                                                            "该标签在 {{count}} 个知识空间中产生",
                                                            { count: row.review_tag_count },
                                                        )}
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                        )}
                                    </td>
                                    {!isPendingTab && (
                                        <td className={cname("px-3 py-3", reviewStatusColorClass(row.status))}>
                                            {row.status === "approved"
                                                ? t("build.tagConsole.statusApproved", "已通过")
                                                : t("build.tagConsole.statusRejected", "已驳回")}
                                        </td>
                                    )}
                                    <td className="max-w-48 px-3 py-3">
                                        {sourceLibraryNames(row.source_files).join("、") || "-"}
                                    </td>
                                    <td className="max-w-64 px-3 py-3">
                                        <SourceFileLinks files={row.source_files} />
                                    </td>
                                    <td className="px-3 py-3">{row.submitter_name || "-"}</td>
                                    <td className="px-3 py-3">{row.reviewer_name || "-"}</td>
                                    <td className="max-w-48 px-3 py-3 text-[#F53F3F]">
                                        {row.reject_reason || "-"}
                                    </td>
                                    <td className="px-3 py-3 text-muted-foreground">
                                        {formatDateTime(row.create_time)}
                                    </td>
                                    <td className="px-3 py-3 text-muted-foreground">
                                        {formatDateTime(row.review_time)}
                                    </td>
                                    {isPendingTab && (
                                        <td className="px-3 py-3">
                                            <Button
                                                size="sm"
                                                variant="link"
                                                className="px-0"
                                                onClick={() => setReviewTarget(refOf(row))}
                                            >
                                                {t("build.tagConsole.handle", "处理")}
                                            </Button>
                                        </td>
                                    )}
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

            <TagReviewDialog
                target={reviewTarget}
                libraries={libraries}
                saving={saving}
                onClose={() => setReviewTarget(null)}
                onApprove={(libraryId, ackSimilar) => reviewTarget && handleApprove(libraryId, [reviewTarget], ackSimilar)}
                onReject={(reason) => reviewTarget && handleReject(reason, [reviewTarget])}
            />
            <BatchApproveLibraryPickerDialog
                open={approveOpen}
                title={t("build.tagConsole.batchApprove", "批量入库")}
                tagNames={actionableRows.map((row) => row.name)}
                libraries={approvableLibraries}
                loading={loadingLibraries}
                emptyHint={t(
                    "build.tagConsole.noSharedLibrary",
                    "当前租户暂无可用标签库。",
                )}
                saving={saving}
                onOpenChange={setApproveOpen}
                onConfirm={(libraryId, ackSimilar) => handleApprove(libraryId, actionableRows.map(refOf), ackSimilar)}
            />
            <RejectReasonDialog
                open={rejectOpen}
                saving={saving}
                onOpenChange={setRejectOpen}
                onConfirm={(reason) => handleReject(reason, actionableRows.map(refOf))}
            />
            <BatchResultDialog result={batchResult} onOpenChange={() => setBatchResult(null)} />
        </div>
    )
}
