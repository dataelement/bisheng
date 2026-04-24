import { useLocalize } from "~/hooks";
import { RefreshCcw } from "lucide-react";
import TextareaAutosize from "react-textarea-autosize";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import cn from "~/utils/cn";
import { generateUUID } from "~/utils";
import { ChannelMinusIcon, ChannelPlusIcon } from "~/components/icons/channels";

const MAX_KEYWORDS_LEN = 200;
const MAX_CONDITIONS_TOTAL = 20;
/** plus.svg / minus.svg 为 32×32 Figma 导出，图形在 viewBox 内略偏左上，缩放后用位移做光学居中 */
const FILTER_COND_ICON_SM = "block h-4 w-4 shrink-0 object-contain translate-x-px translate-y-px";
const FILTER_COND_ICON_MD = "block h-8 w-8 shrink-0 object-contain translate-x-px translate-y-[3px]";

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
    // 主频道可禁用首个条件删除（不显示减号）；子频道默认不禁用
    disableFirstConditionDelete?: boolean;
}

function nanoid() {
    return generateUUID(8);
}

/** 中文分号转英文分号并规范化空白 */
export function normalizeKeywords(raw: string): string {
    return raw
        .replace(/；/g, ";")
        // 把分号两侧的空白归一
        .replace(/\s*;\s*/g, ";")
        // 避免输入时产生连续分号（例如显示为 ";;"）
        .replace(/;{2,}/g, ";");
}

export function countTotalConditions(groups: FilterGroup[]): number {
    return groups.reduce((s, g) => s + g.conditions.length, 0);
}

export function validateFilterGroups(groups: FilterGroup[], localize: (key: string) => string): string | null {
    for (const g of groups) {
        for (const c of g.conditions) {
            if (!c.keywords.trim()) return localize("com_subscription.keyword_cannot_be_empty");
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
    onTopRelationChange,
    disableFirstConditionDelete = false
}: FilterConditionEditorProps) {
    const localize = useLocalize();
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
                message: localize("com_subscription.max_200_characters"),
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
                    className="flex items-center justify-center p-1.5 text-[#86909C] transition-colors w-8"
                    title={localize("com_subscription.add_condition")}
                >
                    <ChannelPlusIcon className={FILTER_COND_ICON_SM} />
                </button>
            </div>
        );
    }

    return (
        <div className="relative isolate pl-10">
            {/* 第一层：And/Or 在线的左侧，虚线不溢出 */}
            {groups.length >= 1 && (
                <>
                    <button
                        type="button"
                        className="group/btn absolute left-0 top-1/2 -translate-y-1/2 z-[1] flex items-center justify-center min-w-[2.5rem] text-[12px] text-[#165DFF] cursor-pointer hover:text-[#4080FF] transition-colors"
                        onClick={() =>
                            onTopRelationChange(topRelation === "and" ? "or" : "and")
                        }
                        onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                onTopRelationChange(topRelation === "and" ? "or" : "and");
                            }
                        }}
                        title={topRelation === "and" ? localize("com_subscription.click_to_switch_to_or") : localize("com_subscription.click_to_switch_to_and")}
                    >
                        <span className="transition-opacity group-hover/btn:opacity-0">
                            {topRelation === "and" ? "And" : "Or"}
                        </span>
                        <RefreshCcw className="absolute size-3.5 opacity-0 group-hover/btn:opacity-100 transition-opacity pointer-events-none" />
                    </button>
                    {/* 第一层连接线：单元素连续圆角括号，更自然 */}
                    <div className="absolute left-9 top-6 bottom-2 w-4 rounded-l-[11px] border-l border-y border-[#C9CDD4]" />
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
                                    className="group/btn absolute left-0 top-1/2 -translate-y-1/2 z-[1] flex items-center justify-center min-w-[2.5rem] text-[12px] text-[#165DFF] cursor-pointer hover:text-[#4080FF] transition-colors"
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
                                    title={group.relation === "and" ? localize("com_subscription.click_to_switch_to_or") : localize("com_subscription.click_to_switch_to_and")}
                                >
                                    <span className="transition-opacity group-hover/btn:opacity-0">
                                        {group.relation === "and" ? "And" : "Or"}
                                    </span>
                                    <RefreshCcw className="absolute size-3.5 opacity-0 group-hover/btn:opacity-100 transition-opacity pointer-events-none" />
                                </button>
                                {/* 第二层连接线：单元素连续圆角括号，更自然 */}
                                <div className="absolute left-9 top-4 bottom-1 w-[21px] rounded-l-[8px] border-l border-y border-[#C9CDD4]" />
                                {!atTotalLimit && (
                                    <button
                                        type="button"
                                        onClick={() => addConditionInGroup(groupIndex)}
                                        className="absolute left-[57px] -bottom-2 flex items-center justify-center w-8 h-8 text-[#86909C] bg-white transition-colors"
                                        title={localize("com_subscription.add_condition_under_current_relation")}
                                    >
                                        <ChannelPlusIcon className={FILTER_COND_ICON_MD} />
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
                                    {/* 包含/不包含：外 6px 圆角，选中项内 4px 圆角 */}
                                    <div className="mt-1 flex flex-shrink-0 rounded-[6px] bg-[#F8F8F8] p-[2px]">
                                        <button
                                            type="button"
                                            onClick={() =>
                                                updateConditionInGroup(groupIndex, condIndex, {
                                                    include: true
                                                })
                                            }
                                            className={cn(
                                                "flex-1 whitespace-nowrap rounded-[4px] px-2 py-1 text-center text-[13px] leading-[22px] transition-colors",
                                                cond.include
                                                    ? "bg-[#335CFF26] text-[#335CFF]"
                                                    : "bg-transparent text-[#818181] hover:bg-[#F2F3F5]"
                                            )}
                                        >{localize("com_subscription.includes")}</button>
                                        <button
                                            type="button"
                                            onClick={() =>
                                                updateConditionInGroup(groupIndex, condIndex, {
                                                    include: false
                                                })
                                            }
                                            className={cn(
                                                "flex-1 whitespace-nowrap rounded-[4px] px-2 py-1 text-center text-[13px] leading-[22px] transition-colors",
                                                !cond.include
                                                    ? "bg-[#335CFF26] text-[#335CFF]"
                                                    : "bg-transparent text-[#818181] hover:bg-[#F2F3F5]"
                                            )}
                                        >{localize("com_subscription.excludes")}</button>
                                    </div>

                                    {/* 关键词输入：单行起步，超出一行时自动向下扩展 */}
                                    <div className="flex-1 min-w-[200px] mt-1 max-w-[620px]">
                                        <TextareaAutosize
                                            value={cond.keywords}
                                            onChange={(e) =>
                                                handleKeywordsChange(
                                                    groupIndex,
                                                    condIndex,
                                                    e.target.value
                                                )
                                            }
                                            minRows={1}
                                            maxRows={4}
                                            placeholder={localize("com_subscription.input_keywords_semicolon_separated")}
                                            className="w-full px-3 py-1 text-[14px] text-[#212121] placeholder:text-[#999999] rounded-lg border border-[#E5E6EB] focus:outline-none focus:ring-2 focus:ring-[#165DFF]/30 focus:border-[#165DFF] resize-none leading-[22px]"
                                        />
                                    </div>

                                    {/* 第一层 & 第二层：可按配置隐藏首个条件删除 */}
                                    <div className="flex items-center gap-1  flex-shrink-0">
                                        {/* 第一层：group 仅 1 条时，这一条既是第一层，也有 + */}
                                        {group.conditions.length === 1 && !atTotalLimit && (
                                            <button
                                                type="button"
                                                onClick={() => addConditionInGroup(groupIndex)}
                                                className="w-8 h-8 flex items-center justify-center text-[#86909C] transition-colors flex-shrink-0"
                                                title={localize("com_subscription.add_condition_under_current_relation")}
                                            >
                                                <ChannelPlusIcon className={FILTER_COND_ICON_MD} />
                                            </button>
                                        )}
                                        {!(
                                            disableFirstConditionDelete &&
                                            groupIndex === 0 &&
                                            condIndex === 0 &&
                                            total === 1
                                        ) && (
                                                <button
                                                    type="button"
                                                    onClick={() =>
                                                        removeConditionInGroup(
                                                            groupIndex,
                                                            condIndex
                                                        )
                                                    }
                                                    className="w-8 h-8 flex items-center justify-center text-[#86909C] hover:text-[#F53F3F] transition-colors flex-shrink-0"
                                                    title={localize("com_subscription.delete_this_condition")}
                                                >
                                                    <ChannelMinusIcon className={FILTER_COND_ICON_MD} />
                                                </button>
                                            )}
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
                        className="flex items-center justify-center w-8 h-8 text-[#165DFF] transition-colors"
                        title={localize("com_subscription.add_condition")}
                    >
                        <ChannelPlusIcon className={FILTER_COND_ICON_MD} />
                    </button>
                </div>
            )}
        </div>
    );
}

/** Legacy validator: flat conditions list */
export function validateFilterConditions(conditions: FilterConditionItem[], localize: (key: string) => string): string | null {
    for (const c of conditions) {
        if (!c.keywords.trim()) return localize("com_subscription.keyword_cannot_be_empty");
    }
    return null;
}

export { MAX_KEYWORDS_LEN, MAX_CONDITIONS_TOTAL };
