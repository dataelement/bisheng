import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { LoadingIcon } from "@/components/bs-icons/loading"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table"
import { ResizableTableHead, TruncatedTableCell } from "@/components/bs-ui/table/TruncatedTableCell"
import { useResizableColumns, type ResizableColumnDef } from "@/components/bs-ui/table/useResizableColumns"
import { TooltipProvider } from "@/components/bs-ui/tooltip"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    deleteAbnormalUpload,
    deleteAbnormalUploads,
    listAbnormalUploadOrgOptions,
    listAbnormalUploads,
    retryAbnormalUpload,
    retryAbnormalUploads,
    type AbnormalUploadItem,
} from "@/controllers/API/abnormalUpload"
import { ClearableFilterSelect } from "../ClearableFilterSelect"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { failureReason } from "./remark"
import UpdateTimeRange from "./UpdateTimeRange"

const COLUMN_DEFS: ResizableColumnDef[] = [
    { defaultWidth: 48, minWidth: 40 },
    { defaultWidth: 180, minWidth: 120 },
    { defaultWidth: 140, minWidth: 100 },
    { defaultWidth: 100, minWidth: 80 },
    { defaultWidth: 100, minWidth: 80 },
    { defaultWidth: 120, minWidth: 90 },
    { defaultWidth: 220, minWidth: 140 },
    { defaultWidth: 160, minWidth: 120 },
    { defaultWidth: 180, minWidth: 140 },
    { defaultWidth: 140, minWidth: 100 },
    { defaultWidth: 140, minWidth: 100 },
    { defaultWidth: 140, minWidth: 100 },
]

const PAGE_SIZE = 20

const LEVEL_OPTIONS = [
    { value: "public", labelKey: "log.abnormalLevelPublic" },
    { value: "department", labelKey: "log.abnormalLevelDepartment" },
    { value: "team", labelKey: "log.abnormalLevelTeam" },
    { value: "team_ks", labelKey: "log.abnormalLevelOffice" },
    { value: "personal", labelKey: "log.abnormalLevelPersonal" },
]

const STATUS_OPTIONS = [
    { value: "3", labelKey: "log.abnormalStatusFailed" },
    { value: "6", labelKey: "log.abnormalStatusTimeout" },
    { value: "7", labelKey: "log.abnormalStatusViolation" },
]

const EMPTY_OPTIONS = {
    companies: [] as string[],
    departments: [] as string[],
    offices: [] as string[],
    knowledges: [] as string[],
    uploaders: [] as string[],
}

function errorText(error: unknown, fallback: string): string {
    if (typeof error === "string" && error.trim()) return error
    if (error instanceof Error && error.message) return error.message
    return fallback
}

export default function AbnormalFilesTab() {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [page, setPage] = useState(1)
    const [total, setTotal] = useState(0)
    const [rows, setRows] = useState<AbnormalUploadItem[]>([])
    const [loading, setLoading] = useState(true)
    const [busy, setBusy] = useState(false)
    const [selected, setSelected] = useState<Set<number>>(new Set())
    const [options, setOptions] = useState(EMPTY_OPTIONS)

    const [statusFilter, setStatusFilter] = useState("")
    const [levelFilter, setLevelFilter] = useState("")
    const [knowledgeFilter, setKnowledgeFilter] = useState("")
    const [uploaderFilter, setUploaderFilter] = useState("")
    const [companyFilter, setCompanyFilter] = useState("")
    const [departmentFilter, setDepartmentFilter] = useState("")
    const [officeFilter, setOfficeFilter] = useState("")
    const [fromFilter, setFromFilter] = useState("")
    const [toFilter, setToFilter] = useState("")
    const [applied, setApplied] = useState({
        status: "",
        level: "",
        knowledge: "",
        uploader: "",
        company: "",
        department: "",
        office: "",
        from: "",
        to: "",
    })

    const notify = (description: string, variant: "success" | "error" = "success") => {
        toast({ title: t("prompt"), description, variant })
    }

    const load = useCallback(async (nextPage: number) => {
        setLoading(true)
        try {
            const result = await listAbnormalUploads({
                page: nextPage,
                page_size: PAGE_SIZE,
                status: applied.status ? Number(applied.status) : undefined,
                space_level: applied.level || undefined,
                knowledge_name: applied.knowledge || undefined,
                uploader_name: applied.uploader || undefined,
                uploader_company: applied.company || undefined,
                uploader_department: applied.department || undefined,
                uploader_office: applied.office || undefined,
                update_time_from: applied.from || undefined,
                update_time_to: applied.to || undefined,
            })
            const items = result?.data || []
            if (items.length === 0 && nextPage > 1) {
                await load(nextPage - 1)
                return
            }
            setRows(items)
            setTotal(result?.total || 0)
            setPage(nextPage)
            setSelected(new Set())
        } catch (error) {
            notify(errorText(error, t("log.abnormalLoadFailed")), "error")
        } finally {
            setLoading(false)
        }
    }, [applied, t])

    useEffect(() => {
        void load(1)
    }, [load])

    useEffect(() => {
        let cancelled = false
        listAbnormalUploadOrgOptions()
            .then((data) => {
                if (!cancelled) {
                    setOptions({
                        companies: data?.companies || [],
                        departments: data?.departments || [],
                        offices: data?.offices || [],
                        knowledges: data?.knowledges || [],
                        uploaders: data?.uploaders || [],
                    })
                }
            })
            .catch(() => {
                if (!cancelled) setOptions(EMPTY_OPTIONS)
            })
        return () => {
            cancelled = true
        }
    }, [])

    const allSelected = rows.length > 0 && rows.every((row) => selected.has(row.file_id))
    const levelLabel = (value: string) => {
        const found = LEVEL_OPTIONS.find((item) => item.value === value)
        return found ? t(found.labelKey) : value
    }
    const statusLabel = (value: number) => {
        const found = STATUS_OPTIONS.find((item) => Number(item.value) === value)
        return found ? t(found.labelKey) : String(value)
    }

    async function runRetry(fileId: number) {
        setBusy(true)
        try {
            await retryAbnormalUpload(fileId)
            notify(t("log.abnormalRetryStarted"))
            await load(page)
        } catch (error) {
            notify(errorText(error, t("log.abnormalActionFailed")), "error")
        } finally {
            setBusy(false)
        }
    }

    async function runDelete(fileId: number) {
        setBusy(true)
        try {
            await deleteAbnormalUpload(fileId)
            notify(t("log.abnormalDeleted"))
            await load(page)
        } catch (error) {
            notify(errorText(error, t("log.abnormalActionFailed")), "error")
        } finally {
            setBusy(false)
        }
    }

    async function runBatchRetry() {
        const fileIds = [...selected]
        if (!fileIds.length || busy) return
        setBusy(true)
        try {
            const result = await retryAbnormalUploads(fileIds)
            const failed = result?.failed || 0
            const retried = result?.retried || 0
            notify(failed
                ? t("log.abnormalBatchRetryPartial", { retried, failed })
                : t("log.abnormalBatchRetryDone", { retried }))
            await load(page)
        } catch (error) {
            notify(errorText(error, t("log.abnormalActionFailed")), "error")
        } finally {
            setBusy(false)
        }
    }

    function runBatchDelete() {
        const fileIds = [...selected]
        if (!fileIds.length || busy) return
        bsConfirm({
            desc: t("log.abnormalBatchDeleteConfirm", { count: fileIds.length }),
            onOk: async (next) => {
                setBusy(true)
                try {
                    const result = await deleteAbnormalUploads(fileIds)
                    const failed = result?.failed || 0
                    const deleted = result?.deleted || 0
                    notify(failed
                        ? t("log.abnormalBatchDeletePartial", { deleted, failed })
                        : t("log.abnormalBatchDeleteDone", { deleted }))
                    await load(page)
                } catch (error) {
                    notify(errorText(error, t("log.abnormalActionFailed")), "error")
                } finally {
                    setBusy(false)
                    next()
                }
            },
        })
    }

    function handleSearch() {
        if (fromFilter && toFilter && fromFilter > toFilter) {
            notify(t("log.abnormalDateOrder"), "error")
            return
        }
        setApplied({
            status: statusFilter,
            level: levelFilter,
            knowledge: knowledgeFilter.trim(),
            uploader: uploaderFilter.trim(),
            company: companyFilter,
            department: departmentFilter,
            office: officeFilter,
            from: fromFilter,
            to: toFilter,
        })
    }

    function handleReset() {
        setStatusFilter("")
        setLevelFilter("")
        setKnowledgeFilter("")
        setUploaderFilter("")
        setCompanyFilter("")
        setDepartmentFilter("")
        setOfficeFilter("")
        setFromFilter("")
        setToFilter("")
        setApplied({
            status: "",
            level: "",
            knowledge: "",
            uploader: "",
            company: "",
            department: "",
            office: "",
            from: "",
            to: "",
        })
    }

    function toggleOne(fileId: number) {
        setSelected((current) => {
            const next = new Set(current)
            if (next.has(fileId)) next.delete(fileId)
            else next.add(fileId)
            return next
        })
    }

    const rc = useResizableColumns(COLUMN_DEFS)
    const headers = [
        "",
        t("log.abnormalFileName"),
        t("log.abnormalKnowledge"),
        t("log.abnormalSpaceLevel"),
        t("log.abnormalStatus"),
        t("log.abnormalUploader"),
        t("log.abnormalReason"),
        t("log.abnormalUpdateTime"),
        t("log.abnormalActions"),
        t("log.abnormalCompany"),
        t("log.abnormalDepartment"),
        t("log.abnormalOffice"),
    ]
    const hasFilter = Object.values(applied).some(Boolean)

    return <div className="audit-pane">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="audit-pane-filters">
            <p className="mb-3 text-sm text-muted-foreground">{t("log.abnormalNote")}</p>
            <div className="mb-4 flex flex-wrap items-center gap-4">
                <div className="w-[160px] relative">
                    <ClearableFilterSelect
                        value={statusFilter}
                        placeholder={t("log.abnormalStatus")}
                        triggerClassName="w-[160px]"
                        options={STATUS_OPTIONS.map((item) => ({ value: item.value, label: t(item.labelKey) }))}
                        onValueChange={setStatusFilter}
                    />
                </div>
                <div className="w-[160px] relative">
                    <ClearableFilterSelect
                        value={levelFilter}
                        placeholder={t("log.abnormalSpaceLevel")}
                        triggerClassName="w-[160px]"
                        options={LEVEL_OPTIONS.map((item) => ({ value: item.value, label: t(item.labelKey) }))}
                        onValueChange={setLevelFilter}
                    />
                </div>
                <div className="w-[180px] relative">
                    <ClearableFilterSelect
                        value={knowledgeFilter}
                        placeholder={t("log.abnormalKnowledge")}
                        triggerClassName="w-[180px]"
                        searchable
                        searchPlaceholder={t("log.abnormalFilterSearch")}
                        options={options.knowledges.map((name) => ({ value: name, label: name }))}
                        onValueChange={setKnowledgeFilter}
                    />
                </div>
                <div className="w-[160px] relative">
                    <ClearableFilterSelect
                        value={uploaderFilter}
                        placeholder={t("log.abnormalUploader")}
                        triggerClassName="w-[160px]"
                        searchable
                        searchPlaceholder={t("log.abnormalFilterSearch")}
                        options={options.uploaders.map((name) => ({ value: name, label: name }))}
                        onValueChange={setUploaderFilter}
                    />
                </div>
                <div className="w-[180px] relative">
                    <ClearableFilterSelect
                        value={companyFilter}
                        placeholder={t("log.abnormalCompany")}
                        triggerClassName="w-[180px]"
                        searchable
                        searchPlaceholder={t("log.abnormalFilterSearch")}
                        options={options.companies.map((name) => ({ value: name, label: name }))}
                        onValueChange={setCompanyFilter}
                    />
                </div>
                <div className="w-[180px] relative">
                    <ClearableFilterSelect
                        value={departmentFilter}
                        placeholder={t("log.abnormalDepartment")}
                        triggerClassName="w-[180px]"
                        searchable
                        searchPlaceholder={t("log.abnormalFilterSearch")}
                        options={options.departments.map((name) => ({ value: name, label: name }))}
                        onValueChange={setDepartmentFilter}
                    />
                </div>
                <div className="w-[180px] relative">
                    <ClearableFilterSelect
                        value={officeFilter}
                        placeholder={t("log.abnormalOffice")}
                        triggerClassName="w-[180px]"
                        searchable
                        searchPlaceholder={t("log.abnormalFilterSearch")}
                        options={options.offices.map((name) => ({ value: name, label: name }))}
                        onValueChange={setOfficeFilter}
                    />
                </div>
                <UpdateTimeRange
                    from={fromFilter}
                    to={toFilter}
                    label={t("log.abnormalUpdateTime")}
                    onChange={(from, to) => {
                        setFromFilter(from)
                        setToFilter(to)
                    }}
                />
                <div>
                    <Button className="mr-3 px-6" onClick={handleSearch} disabled={loading || busy}>{t("log.searchButton")}</Button>
                    <Button variant="outline" className="px-6" onClick={handleReset} disabled={loading || busy}>{t("log.resetButton")}</Button>
                </div>
                <Button
                    type="button"
                    variant="outline"
                    className="border-primary/20 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary"
                    onClick={() => void runBatchRetry()}
                    disabled={busy || selected.size === 0}
                >{t("log.abnormalBatchRetry")}</Button>
                <Button
                    type="button"
                    variant="outline"
                    className="border-red-200 bg-red-50 text-red-600 hover:bg-red-100 hover:text-red-700"
                    onClick={runBatchDelete}
                    disabled={busy || selected.size === 0}
                >{t("log.abnormalBatchDelete")}</Button>
            </div>
        </div>
        <div className="audit-pane-table">
            <TooltipProvider delayDuration={200}>
                <Table variant="filelist" containerClassName="audit-table-scroll" style={{ tableLayout: "fixed", width: rc.totalWidth, minWidth: "100%" }}>
                    <TableHeader>
                        <TableRow>
                            <TableHead {...rc.getThProps(0)}>
                                <input
                                    type="checkbox"
                                    checked={allSelected}
                                    disabled={busy || rows.length === 0}
                                    onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((row) => row.file_id)))}
                                    aria-label={t("log.abnormalSelectPage")}
                                />
                            </TableHead>
                            {headers.slice(1).map((label, index) => (
                                <ResizableTableHead
                                    key={label}
                                    label={label}
                                    columnIndex={index + 1}
                                    lastColumn={index + 1 === headers.length - 1}
                                    thProps={rc.getThProps(index + 1)}
                                    startResize={rc.startResize}
                                />
                            ))}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {rows.map((row) => (
                            <TableRow key={row.file_id}>
                                <TableCell {...rc.getTdProps(0)}>
                                    <input
                                        type="checkbox"
                                        checked={selected.has(row.file_id)}
                                        disabled={busy}
                                        onChange={() => toggleOne(row.file_id)}
                                        aria-label={row.file_name}
                                    />
                                </TableCell>
                                <TruncatedTableCell tdProps={rc.getTdProps(1)} text={row.file_name} />
                                <TruncatedTableCell tdProps={rc.getTdProps(2)} text={row.knowledge_name} />
                                <TruncatedTableCell tdProps={rc.getTdProps(3)} text={levelLabel(row.space_level)} />
                                <TruncatedTableCell tdProps={rc.getTdProps(4)} text={statusLabel(row.status)} />
                                <TruncatedTableCell tdProps={rc.getTdProps(5)} text={row.uploader_name || ""} />
                                <TruncatedTableCell tdProps={rc.getTdProps(6)} text={failureReason(row.status, row.remark || "")} full />
                                <TruncatedTableCell tdProps={rc.getTdProps(7)} text={row.update_time ? row.update_time.replace("T", " ").slice(0, 19) : ""} />
                                <TableCell {...rc.getTdProps(8)} className="whitespace-nowrap">
                                    <Button type="button" size="sm" variant="outline" className="mr-2 border-primary/20 bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary" disabled={busy} onClick={() => void runRetry(row.file_id)}>{t("log.abnormalRetry")}</Button>
                                    <Button type="button" size="sm" variant="outline" className="border-red-200 bg-red-50 text-red-600 hover:bg-red-100 hover:text-red-700" disabled={busy} onClick={() => void runDelete(row.file_id)}>{t("log.abnormalDelete")}</Button>
                                </TableCell>
                                <TruncatedTableCell tdProps={rc.getTdProps(9)} text={row.company_name || ""} />
                                <TruncatedTableCell tdProps={rc.getTdProps(10)} text={row.department_name || ""} />
                                <TruncatedTableCell tdProps={rc.getTdProps(11)} text={row.office_name || ""} />
                            </TableRow>
                        ))}
                    </TableBody>
                    {!rows.length && <TableFooter>
                        <TableRow>
                            <TableCell colSpan={12} className="text-center text-gray-400">
                                {hasFilter ? t("log.abnormalEmptyFiltered") : t("log.abnormalEmpty")}
                            </TableCell>
                        </TableRow>
                    </TableFooter>}
                </Table>
            </TooltipProvider>
        </div>
        <div className="bisheng-table-footer z-20 px-6 bg-background-login">
            <div className="flex items-center gap-2">
                <p className="desc">{t("log.abnormalFiles")}</p>
            </div>
            <AutoPagination
                className="float-right justify-end w-full mr-6"
                page={page}
                pageSize={PAGE_SIZE}
                total={total}
                showTotal
                onChange={(next) => void load(next)}
            />
        </div>
    </div>
}
