import { useLocalize } from "~/hooks";
import { RefreshCcw, SquarePlus } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import cn from "~/utils/cn";
import { generateUUID } from "~/utils";
import { ChannelMinusIcon } from "~/components/icons/channels";

const MAX_KEYWORD_LEN = 50;
const MAX_KEYWORDS_PER_COND = 30;
const MAX_CONDITIONS_TOTAL = 20;
const FILTER_COND_ICON_MD = "block h-8 w-8 shrink-0 object-contain translate-x-px translate-y-[3px]";

export type FilterRelation = "and" | "or";

export interface FilterConditionItem {
    id: string;
    include: boolean; // 包含=true, 不包含=false
    keywords: string[];
}

/**
 * FilterGroup 表示一组条件。
 * 本期不再支持多组嵌套：UI 始终只渲染单组（数组长度恒为 1）。
 * group.relation 即条件之间的关系（and / or），≥ 2 个条件时才在 UI 上展示。
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
    /** 主频道可禁用首个条件删除（不显示减号）；子频道默认不禁用 */
    disableFirstConditionDelete?: boolean;
}

function nanoid() {
    return generateUUID(8);
}

export function countTotalConditions(groups: FilterGroup[]): number {
    return groups.reduce((s, g) => s + g.conditions.length, 0);
}

export function validateFilterGroups(groups: FilterGroup[], localize: (key: string) => string): string | null {
    for (const g of groups) {
        for (const c of g.conditions) {
            if (!Array.isArray(c.keywords) || c.keywords.length === 0) {
                return localize("com_subscription.keyword_cannot_be_empty");
            }
        }
    }
    return null;
}

interface KeywordTagInputProps {
    keywords: string[];
    onChange: (next: string[]) => void;
}

function KeywordTagInput({ keywords, onChange }: KeywordTagInputProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [draft, setDraft] = useState("");
    const inputRef = useRef<HTMLInputElement | null>(null);

    const commit = (raw: string) => {
        const trimmed = raw.trim();
        if (!trimmed) return;
        if (trimmed.length > MAX_KEYWORD_LEN) {
            showToast({
                message: localize("com_subscription.max_200_characters"),
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        if (keywords.length >= MAX_KEYWORDS_PER_COND) {
            showToast({
                message: localize("com_subscription.max_200_characters"),
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        if (keywords.includes(trimmed)) {
            setDraft("");
            return;
        }
        onChange([...keywords, trimmed]);
        setDraft("");
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault();
            commit(draft);
            return;
        }
        if (e.key === "Backspace" && draft === "" && keywords.length > 0) {
            e.preventDefault();
            onChange(keywords.slice(0, -1));
        }
    };

    return (
        <div
            className="min-h-[32px] w-full rounded-[6px] border border-[#EBECF0] bg-white px-[8px] py-[3px] flex flex-wrap items-center gap-[4px] cursor-text focus-within:border-[#165DFF] focus-within:ring-2 focus-within:ring-[#165DFF]/20"
            onClick={() => inputRef.current?.focus()}
        >
            {keywords.map((kw, idx) => (
                <span
                    key={`${kw}-${idx}`}
                    className="inline-flex items-center rounded-[4px] bg-[#F2F3F5] px-[8px] py-[1px] text-[14px] leading-[22px] text-[#4E5969] max-w-[180px] truncate"
                >
                    {kw}
                </span>
            ))}
            <input
                ref={inputRef}
                type="text"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                onBlur={() => commit(draft)}
                placeholder={keywords.length === 0 ? localize("com_subscription.input_keyword_press_enter") : ""}
                className="flex-1 min-w-[80px] bg-transparent text-[14px] text-[#212121] placeholder:text-[#999999] outline-none border-0"
            />
        </div>
    );
}

export function FilterConditionEditor({
    groups,
    topRelation: _topRelation,
    onGroupsChange,
    onTopRelationChange: _onTopRelationChange,
    disableFirstConditionDelete = false,
}: FilterConditionEditorProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();

    // 单层视图：UI 永远只读 / 写第一组。其它组（如果存在）丢弃。
    const group: FilterGroup = groups[0] ?? {
        id: nanoid(),
        relation: "and",
        conditions: [],
    };
    const conditions = group.conditions;
    const total = conditions.length;
    const atTotalLimit = total >= MAX_CONDITIONS_TOTAL;

    const writeGroup = (next: FilterGroup) => {
        onGroupsChange([next]);
    };

    const ensureGroupAndRun = (mutator: (g: FilterGroup) => FilterGroup) => {
        writeGroup(mutator(group));
    };

    const addCondition = () => {
        if (atTotalLimit) {
            showToast({
                message: localize("com_subscription.max_conditions_reached") || "已达条件上限",
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        ensureGroupAndRun((g) => ({
            ...g,
            conditions: [
                ...g.conditions,
                { id: nanoid(), include: true, keywords: [] },
            ],
        }));
    };

    const removeCondition = (condIndex: number) => {
        const nextConditions = conditions.filter((_, i) => i !== condIndex);
        if (nextConditions.length === 0) {
            // 删光最后一条 → 整组移除（让上层联动关闭开关 / 移除子频道）
            onGroupsChange([]);
            return;
        }
        ensureGroupAndRun((g) => ({ ...g, conditions: nextConditions }));
    };

    const updateCondition = (condIndex: number, updates: Partial<FilterConditionItem>) => {
        ensureGroupAndRun((g) => ({
            ...g,
            conditions: g.conditions.map((c, i) =>
                i === condIndex ? { ...c, ...updates } : c
            ),
        }));
    };

    const toggleRelation = () => {
        ensureGroupAndRun((g) => ({
            ...g,
            relation: g.relation === "and" ? "or" : "and",
        }));
    };

    const relationLabel = group.relation === "and"
        ? localize("com_subscription.relation_and")
        : localize("com_subscription.relation_or");
    const relationToggleTitle = group.relation === "and"
        ? localize("com_subscription.click_to_switch_to_or")
        : localize("com_subscription.click_to_switch_to_and");

    // 没有任何条件 / 没有 group：仅展示「添加条件」按钮（与开关刚开启时一致）
    if (groups.length === 0 || conditions.length === 0) {
        return (
            <div className="flex">
                <button
                    type="button"
                    onClick={addCondition}
                    className="inline-flex items-center gap-[4px] rounded-[6px] border border-[#EBECF0] bg-white/50 backdrop-blur-[4px] px-[12px] py-[3px] text-[14px] leading-[22px] text-[#212121] hover:bg-[#F8F8F8]"
                    title={localize("com_subscription.add_condition")}
                >
                    <SquarePlus className="size-4 shrink-0 text-[#212121]" strokeWidth={1.5} />
                    <span>{localize("com_subscription.add_condition")}</span>
                </button>
            </div>
        );
    }

    const showRelationLine = conditions.length >= 2;

    return (
        <div className={cn("relative", showRelationLine && "pl-[34px]")}>
            {/* 关系连线 + 文字（仅 ≥ 2 个条件时显示） */}
            {showRelationLine && (
                <>
                    <button
                        type="button"
                        className="group/btn absolute left-0 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center w-[26px] text-[12px] leading-[20px] text-[#666] cursor-pointer hover:text-[#165DFF] transition-colors whitespace-nowrap"
                        onClick={toggleRelation}
                        onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                toggleRelation();
                            }
                        }}
                        title={relationToggleTitle}
                    >
                        <span className="transition-opacity group-hover/btn:opacity-0">
                            {relationLabel}
                        </span>
                        <RefreshCcw className="absolute size-3.5 opacity-0 group-hover/btn:opacity-100 transition-opacity pointer-events-none text-[#165DFF]" />
                    </button>
                    {/* 连接线（包住所有条件行） */}
                    <div className="pointer-events-none absolute left-[25px] top-[14px] bottom-[14px] w-[9px] rounded-l-[8px] border-l border-y border-[#C9CDD4]" />
                </>
            )}

            <div className="space-y-2">
                {conditions.map((cond, condIndex) => {
                    const showRemove = !(disableFirstConditionDelete && condIndex === 0 && total === 1);
                    return (
                        <div
                            key={cond.id}
                            className="flex items-start gap-[4px]"
                        >
                            {/* 包含 / 不包含 切换 */}
                            <div className="mt-0 flex flex-shrink-0 rounded-[6px] bg-[#F8F8F8] p-[3px]">
                                <button
                                    type="button"
                                    onClick={() => updateCondition(condIndex, { include: true })}
                                    className={cn(
                                        "whitespace-nowrap rounded-[4px] px-[12px] py-[2px] text-center text-[14px] leading-[22px] transition-colors",
                                        cond.include
                                            ? "bg-[#335CFF26] text-[#335CFF] font-medium"
                                            : "bg-transparent text-[#818181] hover:bg-[#F2F3F5]"
                                    )}
                                >
                                    {localize("com_subscription.includes")}
                                </button>
                                <button
                                    type="button"
                                    onClick={() => updateCondition(condIndex, { include: false })}
                                    className={cn(
                                        "whitespace-nowrap rounded-[4px] px-[12px] py-[2px] text-center text-[14px] leading-[22px] transition-colors",
                                        !cond.include
                                            ? "bg-[#335CFF26] text-[#335CFF] font-medium"
                                            : "bg-transparent text-[#818181] hover:bg-[#F2F3F5]"
                                    )}
                                >
                                    {localize("com_subscription.excludes")}
                                </button>
                            </div>

                            {/* 关键词 Tag 输入 */}
                            <div className="flex-1 min-w-0">
                                <KeywordTagInput
                                    keywords={cond.keywords}
                                    onChange={(next) => updateCondition(condIndex, { keywords: next })}
                                />
                            </div>

                            {/* 删除按钮 */}
                            <div className="flex flex-shrink-0">
                                {showRemove && (
                                    <button
                                        type="button"
                                        onClick={() => removeCondition(condIndex)}
                                        className="w-8 h-8 flex items-center justify-center text-[#86909C] hover:text-[#F53F3F] transition-colors"
                                        title={localize("com_subscription.delete_this_condition")}
                                    >
                                        <ChannelMinusIcon className={FILTER_COND_ICON_MD} />
                                    </button>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* 添加条件按钮 */}
            {!atTotalLimit && (
                <div className="mt-[8px]">
                    <button
                        type="button"
                        onClick={addCondition}
                        className="inline-flex items-center gap-[4px] rounded-[6px] border border-[#EBECF0] bg-white/50 backdrop-blur-[4px] px-[12px] py-[3px] text-[14px] leading-[22px] text-[#212121] hover:bg-[#F8F8F8]"
                        title={localize("com_subscription.add_condition")}
                    >
                        <SquarePlus className="size-4 shrink-0 text-[#212121]" strokeWidth={1.5} />
                        <span>{localize("com_subscription.add_condition")}</span>
                    </button>
                </div>
            )}
        </div>
    );
}

export { MAX_KEYWORDS_PER_COND, MAX_KEYWORD_LEN, MAX_CONDITIONS_TOTAL };
