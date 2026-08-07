import FilterByUser from "@/components/bs-comp/filterTableDataComponent/FilterByUser"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { useTranslation } from "react-i18next"
import { EMPTY_FILTERS, RESOURCE_TYPES, type TagConsoleFilterState } from "./tagConsoleTypes"

interface TagFilterBarProps {
    filters: TagConsoleFilterState
    /** Review mode adds the status selector; library mode has a single source. */
    showStatus: boolean
    onChange: (filters: TagConsoleFilterState) => void
    onSearch: () => void
}

/** One labelled control. Fields wrap instead of being squeezed side by side. */
function Field({ label, wide, children }: { label: string; wide?: boolean; children: React.ReactNode }) {
    return (
        <div className={wide ? "w-[360px]" : "w-[200px]"}>
            <Label className="bisheng-label mb-1 block text-xs">{label}</Label>
            {children}
        </div>
    )
}

export function TagFilterBar({ filters, showStatus, onChange, onSearch }: TagFilterBarProps) {
    const { t } = useTranslation()

    const patch = (part: Partial<TagConsoleFilterState>) => onChange({ ...filters, ...part })

    const resourceTypeLabel = (value: string) => {
        if (value === "ai_auto_tag") return t("build.tagSourceAi", "AI标签")
        if (value === "system_tag") return t("build.tagSourceSystem", "系统标签")
        return t("build.tagSourceManual", "人工标签")
    }

    // FilterByUser is a multi-select, but the API takes a single id — keep the
    // last picked value so the control stays usable without a new component.
    const userValue = (id: string) => (id ? [{ label: "", value: id }] : [])
    const pickUser = (options: { value: string }[]) =>
        options?.length ? options[options.length - 1].value : ""

    const dateRange = (
        startKey: "createTimeStart" | "reviewTimeStart",
        endKey: "createTimeEnd" | "reviewTimeEnd",
    ) => (
        <div className="flex items-center gap-1.5">
            <Input
                type="date"
                className="flex-1"
                value={filters[startKey]}
                onChange={(e) => patch({ [startKey]: e.target.value } as Partial<TagConsoleFilterState>)}
            />
            <span className="shrink-0 text-xs text-muted-foreground">{t("build.tagConsole.to", "至")}</span>
            <Input
                type="date"
                className="flex-1"
                value={filters[endKey]}
                onChange={(e) => patch({ [endKey]: e.target.value } as Partial<TagConsoleFilterState>)}
            />
        </div>
    )

    return (
        <div className="border-b border-[#ECECEC] bg-[#FAFBFC] px-4 py-3">
            <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
                <Field label={t("build.tagName", "标签名称")}>
                    <Input
                        value={filters.tagName}
                        placeholder={t("build.tagConsole.tagNamePlaceholder", "请输入标签名称")}
                        onChange={(e) => patch({ tagName: e.target.value })}
                        onKeyDown={(e) => e.key === "Enter" && onSearch()}
                    />
                </Field>

                {showStatus && (
                    <Field label={t("build.tagConsole.status", "标签状态")}>
                        <Select
                            value={filters.status || "all"}
                            onValueChange={(value) => patch({ status: value === "all" ? "" : (value as any) })}
                        >
                            <SelectTrigger>
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="all">{t("build.tagConsole.statusAll", "全部")}</SelectItem>
                                <SelectItem value="pending">{t("build.tagConsole.statusPending", "待审核")}</SelectItem>
                                <SelectItem value="rejected">{t("build.tagConsole.statusRejected", "已驳回")}</SelectItem>
                            </SelectContent>
                        </Select>
                    </Field>
                )}

                <Field label={t("build.tagSource", "标签来源")}>
                    <Select
                        value={filters.resourceType || "all"}
                        onValueChange={(value) => patch({ resourceType: value === "all" ? "" : value })}
                    >
                        <SelectTrigger>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">{t("build.tagConsole.statusAll", "全部")}</SelectItem>
                            {RESOURCE_TYPES.map((value) => (
                                <SelectItem key={value} value={value}>
                                    {resourceTypeLabel(value)}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>

                <Field label={t("build.tagConsole.submitter", "提报者")}>
                    <FilterByUser
                        value={userValue(filters.submitterId)}
                        placeholder={t("build.tagConsole.selectUser", "请选择用户")}
                        onChange={(options: any) => patch({ submitterId: pickUser(options) })}
                    />
                </Field>

                <Field label={t("build.tagConsole.reviewer", "审核者")}>
                    <FilterByUser
                        value={userValue(filters.reviewerId)}
                        placeholder={t("build.tagConsole.selectUser", "请选择用户")}
                        onChange={(options: any) => patch({ reviewerId: pickUser(options) })}
                    />
                </Field>

                <Field label={t("build.tagConsole.createDate", "创建日期")} wide>
                    {dateRange("createTimeStart", "createTimeEnd")}
                </Field>

                <Field label={t("build.tagConsole.reviewDate", "审核日期")} wide>
                    {dateRange("reviewTimeStart", "reviewTimeEnd")}
                </Field>

                <div className="flex items-center gap-2 pb-0.5">
                    <Button onClick={onSearch}>{t("build.tagConsole.search", "搜索")}</Button>
                    <Button
                        variant="outline"
                        onClick={() => {
                            // Clears the filters only; the left panel selection stays.
                            onChange({ ...EMPTY_FILTERS, status: filters.status })
                        }}
                    >
                        {t("build.tagConsole.reset", "重置")}
                    </Button>
                </div>
            </div>
        </div>
    )
}
