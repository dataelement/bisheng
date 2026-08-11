import FilterByUser from "@/components/bs-comp/filterTableDataComponent/FilterByUser"
import KnowledgeSelect from "@/components/bs-comp/selectComponent/knowledge"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import { useTranslation } from "react-i18next"
import {
    EMPTY_PICK,
    RESOURCE_TYPES,
    type TagConsoleFilterState,
    type TagConsolePick,
} from "./tagConsoleTypes"

interface TagFilterBarProps {
    filters: TagConsoleFilterState
    /** Only the reviewed tab has two outcomes to choose between. */
    showStatus: boolean
    onChange: (filters: TagConsoleFilterState) => void
    onSearch: () => void
    /** Clearing the form is expected to show the cleared result straight away. */
    onReset: () => void
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

export function TagFilterBar({ filters, showStatus, onChange, onSearch, onReset }: TagFilterBarProps) {
    const { t } = useTranslation()

    const patch = (part: Partial<TagConsoleFilterState>) => onChange({ ...filters, ...part })

    const resourceTypeLabel = (value: string) => {
        if (value === "ai_auto_tag") return t("build.tagSourceAi", "AI标签")
        if (value === "system_tag") return t("build.tagSourceSystem", "系统标签")
        return t("build.tagSourceManual", "人工标签")
    }

    // The user and knowledge pickers are multi-selects, but the API takes a
    // single id — keep the last picked value so they stay usable without new
    // components. The name has to be carried along: they render the option
    // label, so feeding back an id with an empty label shows an empty box.
    const pickValue = (pick: TagConsolePick) => (pick.id ? [{ label: pick.name, value: pick.id }] : [])
    const pickOne = (options: { label: string; value: string | number }[]): TagConsolePick => {
        if (!options?.length) return EMPTY_PICK
        const picked = options[options.length - 1]
        return { id: String(picked.value), name: picked.label }
    }

    /**
     * A date input only opens its calendar from the small icon by default,
     * which is an easy target to miss. Open it from anywhere in the field.
     *
     * Guarded on both sides: browsers without `showPicker` keep today's
     * icon-only behaviour, and the call throws if the picker is already open.
     */
    const openDatePicker = (event: React.MouseEvent<HTMLInputElement>) => {
        const input = event.currentTarget
        try {
            input.showPicker?.()
        } catch {
            // Already open — nothing to do.
        }
    }

    const dateField = (key: keyof TagConsoleFilterState) => (
        <Input
            type="date"
            className="flex-1 cursor-pointer"
            value={filters[key] as string}
            onClick={openDatePicker}
            onChange={(e) => patch({ [key]: e.target.value } as Partial<TagConsoleFilterState>)}
        />
    )

    const dateRange = (
        startKey: "createTimeStart" | "reviewTimeStart",
        endKey: "createTimeEnd" | "reviewTimeEnd",
    ) => (
        <div className="flex items-center gap-1.5">
            {dateField(startKey)}
            <span className="shrink-0 text-xs text-muted-foreground">{t("build.tagConsole.to", "至")}</span>
            {dateField(endKey)}
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
                                <SelectItem value="approved">{t("build.tagConsole.statusApproved", "已通过")}</SelectItem>
                                <SelectItem value="rejected">{t("build.tagConsole.statusRejected", "已驳回")}</SelectItem>
                            </SelectContent>
                        </Select>
                    </Field>
                )}

                <Field label={t("build.tagConsole.tagType", "标签类型")}>
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

                <Field label={t("build.tagConsole.sourceLibrary", "标签来源库")}>
                    <KnowledgeSelect
                        type="file"
                        value={pickValue(filters.sourceKnowledge)}
                        onChange={(options: any) => patch({ sourceKnowledge: pickOne(options) })}
                    />
                </Field>

                <Field label={t("build.tagConsole.submitter", "提报者")}>
                    <FilterByUser
                        value={pickValue(filters.submitter)}
                        placeholder={t("build.tagConsole.selectUser", "请选择用户")}
                        onChange={(options: any) => patch({ submitter: pickOne(options) })}
                    />
                </Field>

                <Field label={t("build.tagConsole.reviewer", "审核者")}>
                    <FilterByUser
                        value={pickValue(filters.reviewer)}
                        placeholder={t("build.tagConsole.selectUser", "请选择用户")}
                        onChange={(options: any) => patch({ reviewer: pickOne(options) })}
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
                    <Button variant="outline" onClick={onReset}>
                        {t("build.tagConsole.reset", "重置")}
                    </Button>
                </div>
            </div>
        </div>
    )
}
