import { useLocalize } from "~/hooks";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { FilterConditionEditor, type FilterGroup, type FilterRelation } from "./FilterConditionEditor";
import { ChannelEditIcon } from "~/components/icons/channels";
import { getFullWidthLength, truncateByFullWidth } from "~/utils";

const MAX_CHANNEL_NAME = 10;
export interface SubChannelData {
    id: string;
    name: string;
    collapsed: boolean;
    groups: FilterGroup[];
    topRelation: FilterRelation;
}

interface SubChannelBlockProps {
    data: SubChannelData;
    openInEditMode?: boolean;
    onEditModeOpened?: () => void;
    onNameChange: (name: string) => void;
    /**
     * Triggered when user finishes editing the name (blur / Enter).
     * Use it for validations that should not run on every keystroke.
     */
    onNameCommitted?: (name: string) => void;
    onRemove: () => void;
    onToggleCollapse: () => void;
    onGroupsChange: (groups: FilterGroup[]) => void;
    onTopRelationChange: (r: FilterRelation) => void;
    onOverLimit?: () => void;
    onEmptyName?: () => void;
}

export function SubChannelBlock({
    data,
    openInEditMode = false,
    onEditModeOpened,
    onNameChange,
    onNameCommitted,
    onRemove,
    onToggleCollapse,
    onGroupsChange,
    onTopRelationChange,
    onOverLimit,
    onEmptyName
}: SubChannelBlockProps) {
    const localize = useLocalize();
    const [isEditing, setIsEditing] = useState(openInEditMode);
    const [editVal, setEditVal] = useState(data.name);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (openInEditMode && inputRef.current) {
            inputRef.current.focus();
            inputRef.current.select();
            onEditModeOpened?.();
        }
    }, [openInEditMode, onEditModeOpened]);

    const handleSave = () => {
        const v = editVal.trim();
        if (!v) {
            onEmptyName?.();
            return;
        }
        onNameChange(v);
        onNameCommitted?.(v);
        setIsEditing(false);
    };

    const handleNameChange = (val: string) => {
        const next = getFullWidthLength(val) > MAX_CHANNEL_NAME ? truncateByFullWidth(val, MAX_CHANNEL_NAME) : val;
        if (getFullWidthLength(val) > MAX_CHANNEL_NAME) onOverLimit?.();

        // Sync immediately so parent state is always up to date when user clicks submit
        // (blur might not have fired yet depending on click timing).
        setEditVal(next);
        onNameChange(next);
    };

    return (
        <div className="overflow-hidden">
            <div className="h-12 flex items-center justify-between gap-2 px-3 bg-[#F8F8F8]">
                <button
                    type="button"
                    onClick={onToggleCollapse}
                    className="w-6 h-6 flex items-center justify-center text-[#86909C] hover:text-[#4E5969] flex-shrink-0"
                >
                    {data.collapsed ? (
                        <ChevronRight className="size-4" />
                    ) : (
                        <ChevronDown className="size-4" />
                    )}
                </button>
                {isEditing ? (
                    <input
                        ref={inputRef}
                        value={editVal}
                        onChange={(e) => handleNameChange(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={(e) => e.key === "Enter" && handleSave()}
                        className="h-[26px] flex-1 min-w-0 px-2 text-[14px] text-[#212121] placeholder:text-[#999999] border border-[#E5E6EB] rounded focus:outline-none focus:ring-1 focus:ring-[#165DFF]"
                        placeholder={localize("com_subscription.sub_channel_name")}
                    />
                ) : (
                    <div
                        className="h-[26px] flex-1 flex items-center gap-1 cursor-pointer group min-w-0"
                        onClick={() => {
                            setEditVal(data.name);
                            setIsEditing(true);
                        }}
                    >
                        <span className="text-[14px] text-[#1D2129] truncate">{data.name}</span>
                        <ChannelEditIcon className="w-4 h-4 opacity-0 group-hover:opacity-100 flex-shrink-0" />
                    </div>
                )}
                <button
                    type="button"
                    onClick={onRemove}
                    className="flex items-center gap-1 text-[14px] text-[#86909C] hover:text-[#F53F3F] flex-shrink-0"
                >{localize("com_subscription.delete")}</button>
            </div>
            {!data.collapsed && (
                <div className="border-t border-[#E5E6EB]">
                    <p className="px-3 pt-3 pb-1 text-[14px] leading-[22px] text-[#666]">
                        {localize("com_subscription.set_article_filter_conditions")}
                    </p>
                    <div className="px-3 pb-3">
                        <FilterConditionEditor
                            groups={data.groups}
                            topRelation={data.topRelation}
                            onGroupsChange={onGroupsChange}
                            onTopRelationChange={onTopRelationChange}
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
