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

export function TagFilterBar({ filters, showStatus, onChange, onSearch }: TagFilterBarProps) {
    const { t } = useTranslation()

    const patch = (part: Partial<TagConsoleFilterState>) => onChange({ ...filters, ...part })

    const resourceTypeLabel = (value: string) => {
        if (value === "ai_auto_tag") return t("build.tagSourceAi", "AI标签")
        if (value === "system_tag") return t("build.tagSourceSystem", "系统标签")
        return t("build.tagSourceManual", "人工标签")
    }

    return (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3 border-b border-[#ECECEC] p-4">
            <div>
                <Label className="bisheng-label">{t("build.tagName", "标签名称")}</Label>
                <Input
                    className="mt-1"
                    value={filters.tagName}
                    onChange={(e) => patch({ tagName: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && onSearch()}
                />
            </div>

            {showStatus && (
                <div>
                    <Label className="bisheng-label">{t("build.tagConsole.status", "标签状态")}</Label>
                    <Select
                        value={filters.status || "all"}
                        onValueChange={(value) => patch({ status: value === "all" ? "" : (value as any) })}
                    >
                        <SelectTrigger className="mt-1">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">{t("build.tagConsole.statusAll", "全部")}</SelectItem>
                            <SelectItem value="pending">{t("build.tagConsole.statusPending", "待审核")}</SelectItem>
                            <SelectItem value="rejected">{t("build.tagConsole.statusRejected", "已驳回")}</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            )}

            <div>
                <Label className="bisheng-label">{t("build.tagSource", "标签来源")}</Label>
                <Select
                    value={filters.resourceType || "all"}
                    onValueChange={(value) => patch({ resourceType: value === "all" ? "" : value })}
                >
                    <SelectTrigger className="mt-1">
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
            </div>

            <div>
                <Label className="bisheng-label">{t("build.tagConsole.createDate", "创建日期")}</Label>
                <div className="mt-1 flex items-center gap-1">
                    <Input
                        type="date"
                        value={filters.createTimeStart}
                        onChange={(e) => patch({ createTimeStart: e.target.value })}
                    />
                    <span className="text-xs text-muted-foreground">{t("build.tagConsole.to", "至")}</span>
                    <Input
                        type="date"
                        value={filters.createTimeEnd}
                        onChange={(e) => patch({ createTimeEnd: e.target.value })}
                    />
                </div>
            </div>

            <div>
                <Label className="bisheng-label">{t("build.tagConsole.reviewDate", "审核日期")}</Label>
                <div className="mt-1 flex items-center gap-1">
                    <Input
                        type="date"
                        value={filters.reviewTimeStart}
                        onChange={(e) => patch({ reviewTimeStart: e.target.value })}
                    />
                    <span className="text-xs text-muted-foreground">{t("build.tagConsole.to", "至")}</span>
                    <Input
                        type="date"
                        value={filters.reviewTimeEnd}
                        onChange={(e) => patch({ reviewTimeEnd: e.target.value })}
                    />
                </div>
            </div>

            <div className="flex items-end gap-2">
                <Button onClick={onSearch}>{t("build.tagConsole.search", "搜索")}</Button>
                <Button
                    variant="outline"
                    onClick={() => {
                        // Reset clears the filters only; the left panel selection stays.
                        onChange({ ...EMPTY_FILTERS, status: filters.status })
                    }}
                >
                    {t("build.tagConsole.reset", "重置")}
                </Button>
            </div>
        </div>
    )
}
