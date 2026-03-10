import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { FilterConditionEditor, type FilterGroup, type FilterRelation } from "./FilterConditionEditor";

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
    onRemove,
    onToggleCollapse,
    onGroupsChange,
    onTopRelationChange,
    onOverLimit,
    onEmptyName
}: SubChannelBlockProps) {
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
        setIsEditing(false);
    };

    const handleNameChange = (val: string) => {
        if (val.length > MAX_CHANNEL_NAME) {
            onOverLimit?.();
            setEditVal(val.slice(0, MAX_CHANNEL_NAME));
        } else {
            setEditVal(val);
        }
    };

    return (
        <div className="border border-t-[#E5E6EB] overflow-hidden">
            <div className="flex items-center justify-between gap-2 px-3 py-2 bg-[#F7F8FA]">
                <button
                    type="button"
                    onClick={onToggleCollapse}
                    className="p-1 text-[#86909C] hover:text-[#4E5969] flex-shrink-0"
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
                        className="flex-1 min-w-0 px-2 py-1 text-[14px] border border-[#E5E6EB] rounded focus:outline-none focus:ring-1 focus:ring-[#165DFF]"
                        placeholder="子频道名称"
                    />
                ) : (
                    <div
                        className="flex-1 flex items-center gap-1 cursor-pointer group min-w-0"
                        onClick={() => {
                            setEditVal(data.name);
                            setIsEditing(true);
                        }}
                    >
                        <span className="text-[14px] text-[#1D2129] truncate">{data.name}</span>
                        <Pencil className="size-3.5 text-[#86909C] opacity-0 group-hover:opacity-100 flex-shrink-0" />
                    </div>
                )}
                <button
                    type="button"
                    onClick={onRemove}
                    className="flex items-center gap-1 text-[14px] text-[#86909C] hover:text-[#F53F3F] flex-shrink-0"
                >
                    删除
                </button>
            </div>
            {!data.collapsed && (
                <div className="p-3 border-t border-[#E5E6EB]">
                    <FilterConditionEditor
                        groups={data.groups}
                        topRelation={data.topRelation}
                        onGroupsChange={onGroupsChange}
                        onTopRelationChange={onTopRelationChange}
                    />
                </div>
            )}
        </div>
    );
}
