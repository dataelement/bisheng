import { Minus, Plus, RefreshCcw } from "lucide-react";
import TextareaAutosize from "react-textarea-autosize";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import cn from "~/utils/cn";
import { generateUUID } from "~/utils";

const MAX_KEYWORDS_LEN = 200;
const MAX_CONDITIONS_TOTAL = 20;

export type FilterRelation = "and" | "or";

export interface FilterConditionItem {
    id: string;
    include: boolean; // 包含=true, 不包含=false
    keywords: string;
}

/**
 * FilterGroup 表示一组被括号包起来的条件。
 * group.relation 是组内 AND / OR；
 * 顶层还有一个 topRelation（组与组之间的关系，只显示一次）。
 */
export interface FilterGroup {
    id: string;
    relation: FilterRelation;
    conditions: FilterConditionItem[];
}

interface FilterConditionEditorProps {
    groups: FilterGroup[];
    topRelation: FilterRelation;
    onGroupsChange: (groups: FilterGroup[]) => void;
    onTopRelationChange: (relation: FilterRelation) => void;
}

function nanoid() {
    return generateUUID(8);
}

/** 中文分号转英文分号并规范化空白 */
export function normalizeKeywords(raw: string): string {
    return raw.replace(/；/g, ";").replace(/\s*;\s*/g, ";").replace(/^;|;$/g, "");
}

export function countTotalConditions(groups: FilterGroup[]): number {
    return groups.reduce((s, g) => s + g.conditions.length, 0);
}

export function validateFilterGroups(groups: FilterGroup[]): string | null {
    for (const g of groups) {
        for (const c of g.conditions) {
            if (!c.keywords.trim()) return "关键词不能为空";
        }
    }
    return null;
}

// 兼容旧版：平铺条件 + 单 relation 转成单组
export function flatToGroups(
    conditions: FilterConditionItem[],
    relation: FilterRelation
): FilterGroup[] {
    if (conditions.length === 0) {
        return [
            {
                id: nanoid(),
                relation: "and",
                conditions: [{ id: nanoid(), include: true, keywords: "" }]
            }
        ];
    }
    return [{ id: nanoid(), relation, conditions }];
}

export function groupsToFlat(groups: FilterGroup[]): {
    conditions: FilterConditionItem[];
    relation: FilterRelation;
} {
    if (groups.length === 0) return { conditions: [], relation: "and" };
    const first = groups[0];
    if (groups.length === 1) return { conditions: first.conditions, relation: first.relation };
    const conditions = groups.flatMap((g) => g.conditions);
    return { conditions, relation: first.relation };
}

export function FilterConditionEditor({
    groups,
    topRelation,
    onGroupsChange,
    onTopRelationChange
}: FilterConditionEditorProps) {
    const total = countTotalConditions(groups);
    const atTotalLimit = total >= MAX_CONDITIONS_TOTAL;
    const { showToast } = useToastContext();

    const addRootCondition = () => {
        if (atTotalLimit) return;
        onGroupsChange([
            ...groups,
            {
                id: nanoid(),
                relation: topRelation === "and" ? "or" : "and",
                conditions: [{ id: nanoid(), include: true, keywords: "" }]
            }
        ]);
    };

    const addConditionInGroup = (groupIndex: number) => {
        if (atTotalLimit) return;
        const next = groups.map((g, i) =>
            i === groupIndex
                ? {
                    ...g,
                    conditions: [
                        ...g.conditions,
                        { id: nanoid(), include: true, keywords: "" }
                    ]
                }
                : g
        );
        onGroupsChange(next);
    };

    const removeConditionInGroup = (groupIndex: number, condIndex: number) => {
        const group = groups[groupIndex];
        if (!group) return;

        const nextGroups = [...groups];
        const nextConditions = group.conditions.filter((_, i) => i !== condIndex);

        if (nextConditions.length === 0) {
            // 删光这一组，整体移除 group
            nextGroups.splice(groupIndex, 1);
        } else {
            nextGroups[groupIndex] = { ...group, conditions: nextConditions };
        }

        onGroupsChange(nextGroups);
    };

    const updateConditionInGroup = (
        groupIndex: number,
        condIndex: number,
        updates: Partial<FilterConditionItem>
    ) => {
        const next = groups.map((g, i) =>
            i === groupIndex
                ? {
                    ...g,
                    conditions: g.conditions.map((c, j) =>
                        j === condIndex ? { ...c, ...updates } : c
                    )
                }
                : g
        );
        onGroupsChange(next);
    };

    const setGroupRelation = (groupIndex: number, relation: FilterRelation) => {
        const next = groups.map((g, i) => (i === groupIndex ? { ...g, relation } : g));
        onGroupsChange(next);
    };

    const handleKeywordsChange = (
        groupIndex: number,
        condIndex: number,
        value: string
    ) => {
        const normalized = normalizeKeywords(value);
        if (normalized.length > MAX_KEYWORDS_LEN) {
            showToast({
                message: "最多输入200个字符",
                severity: NotificationSeverity.WARNING
            });
            updateConditionInGroup(groupIndex, condIndex, {
                keywords: normalized.slice(0, MAX_KEYWORDS_LEN)
            });
        } else {
            updateConditionInGroup(groupIndex, condIndex, { keywords: normalized });
        }
    };

    if (!groups.length) {
        return (
            <div className="flex">
                <button
                    type="button"
                    onClick={addRootCondition}
                    className="flex items-center justify-center p-1.5 rounded border border-[#E5E6EB] text-[#86909C] hover:border-[#165DFF] hover:text-[#165DFF] transition-colors w-8"
                    title="新增条件"
                >
                    <Plus className="size-4" />
                </button>
            </div>
        );
    }

    return (
        <div className="relative pl-10">
            {/* 第一层：And/Or 在线的左侧，虚线不溢出 */}
            {groups.length >= 1 && (
                <>
                    <button
                        type="button"
                        className="group/btn absolute left-0 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center min-w-[2.5rem] text-[12px] text-[#165DFF] cursor-pointer hover:text-[#4080FF] transition-colors"
                        onClick={() =>
                            onTopRelationChange(topRelation === "and" ? "or" : "and")
                        }
                        onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                onTopRelationChange(topRelation === "and" ? "or" : "and");
                            }
                        }}
                        title={topRelation === "and" ? "点击切换为 Or" : "点击切换为 And"}
                    >
                        <span className="transition-opacity group-hover/btn:opacity-0">
                            {topRelation === "and" ? "And" : "Or"}
                        </span>
                        <RefreshCcw className="absolute size-3.5 opacity-0 group-hover/btn:opacity-100 transition-opacity pointer-events-none" />
                    </button>
                    {/* 竖线延伸至最下方加号，底横线指向加号 */}
                    <div className="absolute left-9 top-6 bottom-4 w-px border-l border-dashed border-[#C9CDD4]" />
                    <div className="absolute left-9 top-6 w-3 h-px border-t border-dashed border-[#C9CDD4]" />
                    <div className="absolute left-9 bottom-4 w-4 h-px border-t border-dashed border-[#C9CDD4]" />
                </>
            )}

            <div className="space-y-3">
                {groups.map((group, groupIndex) => (
                    <div key={group.id} className="relative pl-10 pb-6">
                        {/* 第二层：And/OR 在线的左侧，虚线包住当前组；底部小括号指向本层新增条件的加号 */}
                        {group.conditions.length > 1 && (
                            <>
                                <button
                                    type="button"
                                    className="group/btn absolute left-0 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center min-w-[2.5rem] text-[12px] text-[#165DFF] cursor-pointer hover:text-[#4080FF] transition-colors"
                                    onClick={() =>
                                        setGroupRelation(
                                            groupIndex,
                                            group.relation === "and" ? "or" : "and"
                                        )
                                    }
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter" || e.key === " ") {
                                            e.preventDefault();
                                            setGroupRelation(
                                                groupIndex,
                                                group.relation === "and" ? "or" : "and"
                                            );
                                        }
                                    }}
                                    title={group.relation === "and" ? "点击切换为 Or" : "点击切换为 And"}
                                >
                                    <span className="transition-opacity group-hover/btn:opacity-0">
                                        {group.relation === "and" ? "And" : "Or"}
                                    </span>
                                    <RefreshCcw className="absolute size-3.5 opacity-0 group-hover/btn:opacity-100 transition-opacity pointer-events-none" />
                                </button>
                                {/* 竖线从组内第一条顶部到底部横线（横线下方是 + 行） */}
                                <div className="absolute left-9 top-4 bottom-4 w-px border-l border-dashed border-[#C9CDD4]" />
                                {/* 顶部小横线包住第一条条件 */}
                                <div className="absolute left-9 top-4 w-3 h-px border-t border-dashed border-[#C9CDD4]" />
                                {/* 底部小横线指向底部的 + 号（与 + 位于同一行上方） */}
                                <div className="absolute left-9 bottom-4 w-3 h-px border-t border-dashed border-[#C9CDD4]" />
                                {!atTotalLimit && (
                                    <button
                                        type="button"
                                        onClick={() => addConditionInGroup(groupIndex)}
                                        className="absolute left-14 bottom-1 flex items-center justify-center w-5 h-5 rounded border border-[#E5E6EB] text-[#86909C] bg-white hover:border-[#165DFF] hover:text-[#165DFF] transition-colors"
                                        title="在当前关系下新增一条条件"
                                    >
                                        <Plus className="size-4" />
                                    </button>
                                )}
                            </>
                        )}

                        <div className="pl-4 space-y-2">
                            {group.conditions.map((cond, condIndex) => (
                                <div
                                    key={cond.id}
                                    className={cn(
                                        "flex items-start gap-2",
                                        group.conditions.length === 1 && "-ml-8"
                                    )}
                                >
                                    {/* 包含/不包含 */}
                                    <div className="flex rounded-lg mt-1 border border-[#E5E6EB] overflow-hidden flex-shrink-0">
                                        <button
                                            type="button"
                                            onClick={() =>
                                                updateConditionInGroup(groupIndex, condIndex, {
                                                    include: true
                                                })
                                            }
                                            className={cn(
                                                "px-3 py-1.5 text-[13px] transition-colors",
                                                cond.include
                                                    ? "bg-[#E8F3FF] text-[#165DFF]"
                                                    : "bg-white text-[#4E5969] hover:bg-[#F2F3F5]"
                                            )}
                                        >
                                            包含
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() =>
                                                updateConditionInGroup(groupIndex, condIndex, {
                                                    include: false
                                                })
                                            }
                                            className={cn(
                                                "px-3 py-1.5 text-[13px] transition-colors",
                                                !cond.include
                                                    ? "bg-[#E8F3FF] text-[#165DFF]"
                                                    : "bg-white text-[#4E5969] hover:bg-[#F2F3F5]"
                                            )}
                                        >
                                            不包含
                                        </button>
                                    </div>

                                    {/* 关键词输入：底纹、200 字上限、中文分号转英文、自适应高度，输入框大一些 */}
                                    <div className="flex-1 min-w-[200px] max-w-[620px]">
                                        <TextareaAutosize
                                            value={cond.keywords}
                                            onChange={(e) =>
                                                handleKeywordsChange(
                                                    groupIndex,
                                                    condIndex,
                                                    e.target.value
                                                )
                                            }
                                            placeholder='请输入关键词, 以分号";"分隔'
                                            className="w-full min-h-[36px] max-h-[120px] px-3 py-2 text-[14px] rounded-lg border border-[#E5E6EB] resize-none focus:outline-none focus:ring-2 focus:ring-[#165DFF]/30 focus:border-[#165DFF]"
                                            rows={1}
                                        />
                                    </div>

                                    {/* 第一层 & 第二层：所有条目都可以删；仅当全局只剩 1 条时不展示 - */}
                                    <div className="flex items-center gap-1 mt-0.5 flex-shrink-0">
                                        {/* 第一层：group 仅 1 条时，这一条既是第一层，也有 + */}
                                        {group.conditions.length === 1 && !atTotalLimit && (
                                            <button
                                                type="button"
                                                onClick={() => addConditionInGroup(groupIndex)}
                                                className="p-1.5 rounded border border-[#E5E6EB] text-[#86909C] hover:border-[#165DFF] hover:text-[#165DFF] transition-colors"
                                                title="在当前关系下新增一条条件"
                                            >
                                                <Plus className="size-4" />
                                            </button>
                                        )}
                                        <button
                                            type="button"
                                            onClick={() =>
                                                removeConditionInGroup(
                                                    groupIndex,
                                                    condIndex
                                                )
                                            }
                                            className="p-1.5 rounded border border-[#E5E6EB] text-[#86909C] hover:text-[#F53F3F] transition-colors"
                                            title="删除该条条件"
                                        >
                                            <Minus className="size-4" />
                                        </button>

                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
            </div>

            {/* 顶层新增条件：第一层最下面的线指向此加号 */}
            {!atTotalLimit && (
                <div className="mt-3 pl-4 flex items-center">
                    <button
                        type="button"
                        onClick={addRootCondition}
                        className="flex items-center justify-center p-1.5 rounded border border-[#E5E6EB] text-[#86909C] hover:border-[#165DFF] hover:text-[#165DFF] transition-colors w-6 h-6"
                        title="新增条件"
                    >
                        <Plus className="size-4" />
                    </button>
                </div>
            )}
        </div>
    );
}

/** 兼容旧校验：平铺条件 */
export function validateFilterConditions(conditions: FilterConditionItem[]): string | null {
    for (const c of conditions) {
        if (!c.keywords.trim()) return "关键词不能为空";
    }
    return null;
}

export { MAX_KEYWORDS_LEN, MAX_CONDITIONS_TOTAL };
