import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { SearchInput } from "@/components/bs-ui/input"
import { cname } from "@/components/bs-ui/utils"
import {
    getGroupedKnowledgeSpacesApi,
    type GroupedKnowledgeSpace,
} from "@/controllers/API/knowledgeSpace"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { ChevronDown, ChevronRight } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

interface KnowledgePickerDialogProps {
    open: boolean
    /** Already attached; shown checked and disabled so they cannot be added twice. */
    excludeIds: number[]
    saving?: boolean
    onOpenChange: (open: boolean) => void
    onConfirm: (knowledgeIds: number[]) => void
}

interface PickerGroup {
    key: string
    title: string
    spaces: GroupedKnowledgeSpace[]
}

/**
 * Knowledge-space picker in the four groups the knowledge sidebar uses.
 *
 * Two levels only — group, then space. The sidebar's own tree goes deeper into
 * folders, but a tag library attaches to a whole space, so folders would be
 * choices the caller cannot act on.
 */
export function KnowledgePickerDialog({
    open,
    excludeIds,
    saving,
    onOpenChange,
    onConfirm,
}: KnowledgePickerDialogProps) {
    const { t } = useTranslation()
    const [keyword, setKeyword] = useState("")
    const [loading, setLoading] = useState(false)
    const [groups, setGroups] = useState<PickerGroup[]>([])
    const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
    const [checkedIds, setCheckedIds] = useState<number[]>([])

    useEffect(() => {
        if (!open) return
        setKeyword("")
        setCheckedIds([])
        setLoading(true)
        let cancelled = false
        void (async () => {
            const res = await captureAndAlertRequestErrorHoc(getGroupedKnowledgeSpacesApi())
            if (cancelled) return
            setGroups(
                res
                    ? [
                          {
                              key: "public",
                              title: t("build.tagConsole.publicSpaces", "公共知识库"),
                              spaces: res.publicSpaces,
                          },
                          {
                              key: "department",
                              title: t("build.tagConsole.departmentSpaces", "部门知识库"),
                              spaces: res.departmentSpaces,
                          },
                          {
                              key: "team",
                              title: t("build.tagConsole.teamSpaces", "团队/科室知识库"),
                              spaces: res.teamSpaces,
                          },
                          {
                              key: "personal",
                              title: t("build.tagConsole.personalSpaces", "个人知识库"),
                              // Favourites is a view over other spaces rather than a
                              // space that holds files, so binding a tag library to it
                              // would attach to nothing.
                              spaces: res.personalSpaces.filter((space) => !space.is_favorite),
                          },
                      ]
                    : [],
            )
            setLoading(false)
        })()
        return () => {
            cancelled = true
        }
    }, [open, t])

    const excluded = useMemo(() => new Set(excludeIds.map(Number)), [excludeIds])

    const visibleGroups = useMemo(() => {
        const trimmed = keyword.trim().toLowerCase()
        if (!trimmed) return groups
        return groups
            .map((group) => ({
                ...group,
                spaces: group.spaces.filter((space) => (space.name || "").toLowerCase().includes(trimmed)),
            }))
            .filter((group) => group.spaces.length > 0)
    }, [groups, keyword])

    const handleToggle = (spaceId: number, checked: boolean) => {
        setCheckedIds((prev) => (checked ? [...prev, spaceId] : prev.filter((id) => id !== spaceId)))
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[520px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.tagConsole.addKnowledge", "添加知识库")}</DialogTitle>
                </DialogHeader>
                <div className="px-6 py-4">
                    <SearchInput
                        placeholder={t("build.tagConsole.searchKnowledge", "搜索知识库")}
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                    />
                    <div className="mt-3 max-h-80 overflow-y-auto rounded-md border border-[#E5E6EB] bg-background p-2">
                        {loading ? (
                            <p className="py-8 text-center text-sm text-muted-foreground">{t("loading")}</p>
                        ) : !visibleGroups.length ? (
                            <p className="py-8 text-center text-sm text-muted-foreground">
                                {t("build.tagConsole.noKnowledge", "暂无知识库")}
                            </p>
                        ) : (
                            visibleGroups.map((group) => {
                                const isCollapsed = collapsed[group.key] ?? false
                                return (
                                    <div key={group.key} className="mb-1">
                                        <button
                                            type="button"
                                            className="flex w-full items-center gap-1 rounded px-1 py-1.5 text-sm font-medium hover:bg-[#F2F3F5]"
                                            onClick={() =>
                                                setCollapsed((prev) => ({ ...prev, [group.key]: !isCollapsed }))
                                            }
                                        >
                                            {isCollapsed ? (
                                                <ChevronRight className="size-4 text-muted-foreground" />
                                            ) : (
                                                <ChevronDown className="size-4 text-muted-foreground" />
                                            )}
                                            {group.title}
                                            <span className="text-xs text-muted-foreground">
                                                ({group.spaces.length})
                                            </span>
                                        </button>
                                        {!isCollapsed &&
                                            group.spaces.map((space) => {
                                                const alreadyBound = excluded.has(Number(space.id))
                                                return (
                                                    <label
                                                        key={space.id}
                                                        className={cname(
                                                            "flex items-center gap-2 rounded py-1.5 pl-7 pr-2 text-sm",
                                                            alreadyBound
                                                                ? "text-muted-foreground"
                                                                : "cursor-pointer hover:bg-[#F2F3F5]",
                                                        )}
                                                    >
                                                        <Checkbox
                                                            checked={
                                                                alreadyBound ||
                                                                checkedIds.includes(Number(space.id))
                                                            }
                                                            disabled={alreadyBound}
                                                            onCheckedChange={(checked) =>
                                                                handleToggle(Number(space.id), Boolean(checked))
                                                            }
                                                        />
                                                        <span className="min-w-0 flex-1 truncate">{space.name}</span>
                                                        {alreadyBound && (
                                                            <span className="shrink-0 text-xs">
                                                                {t("build.tagConsole.alreadyBound", "已关联")}
                                                            </span>
                                                        )}
                                                    </label>
                                                )
                                            })}
                                    </div>
                                )
                            })
                        )}
                    </div>
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button
                        className="px-8"
                        disabled={saving || !checkedIds.length}
                        onClick={() => onConfirm(checkedIds)}
                    >
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
