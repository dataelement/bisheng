import {
    BookText,
    MinimizeIcon,
    MoreHorizontal,
    Pin,
    PinOff,
    Settings,
    Users,
    LogOut,
} from "lucide-react";
import { useState } from "react";
import { KnowledgeSpace, SpaceRole } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import { useConfirm, useToastContext } from "~/Providers";

interface KnowledgeSpaceItemProps {
    space: KnowledgeSpace;
    isActive: boolean;
    type: "created" | "joined";
    onSelect: (space: KnowledgeSpace) => void;
    onUpdate: (space: KnowledgeSpace) => void;
    onDelete: (id: string) => void;
    onLeave: (id: string) => void;
    onPin: (id: string, pinned: boolean) => void;
    onSettings?: (space: KnowledgeSpace) => void;
}

export default function KnowledgeSpaceItem({
    space,
    isActive,
    type,
    onSelect,
    onUpdate,
    onDelete,
    onLeave,
    onPin,
    onSettings,
}: KnowledgeSpaceItemProps) {
    const [isEditing, setIsEditing] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const { showToast } = useToastContext();
    const confirm = useConfirm()

    const rename = (e) => {
        const newName = e.target.value.trim();
        setIsEditing(false);
        if (!newName) return
        if (newName.length > 10) {
            return showToast({
                message: "最多输入 10 个字符",
                severity: NotificationSeverity.ERROR
            });
        }
        if (newName && newName !== space.name) {
            onUpdate({ ...space, name: newName });
        }
    }

    return (
        <div
            className={`group flex items-center justify-between h-8 px-3 py-1.5 rounded-lg cursor-pointer transition-all border ${isActive
                ? "bg-[#E6EDFC] border-primary shadow-sm"
                : "border-transparent hover:bg-[#F7F7F7]"
                }`}
            onClick={() => !isEditing && onSelect(space)}
        >
            <div className="flex items-center gap-1 flex-1 min-w-0">
                <div className={`flex-shrink-0 flex items-center justify-center size-5 rounded-md ${isActive ? "bg-white border border-[#165dff]/20 shadow-sm" : ""}`}>
                    <BookText className={`size-3 ${isActive ? "text-[#165dff]" : "text-[#86909c]"}`} />
                </div>

                {isEditing ? (
                    <input
                        type="text"
                        defaultValue={space.name}
                        className="flex-1 px-1 min-w-0 text-[14px] bg-white rounded focus:outline-none"
                        autoFocus
                        onBlur={rename}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") e.currentTarget.blur();
                            else if (e.key === "Escape") setIsEditing(false);
                        }}
                        onClick={(e) => e.stopPropagation()}
                    />
                ) : (
                    <div className="flex items-center gap-1 flex-1 min-w-0">
                        <span onDoubleClick={() => setIsEditing(true)} className="text-[14px] truncate text-[#1d2129]">
                            {space.name}
                        </span>
                    </div>
                )}
            </div>

            <div className="flex items-center justify-end flex-shrink-0 w-8 h-5 relative">
                {space.isPinned && (
                    <div className={`
                        absolute right-0 flex items-center justify-center p-1 pointer-events-none
                        transition-opacity duration-200
                        ${menuOpen ? "opacity-0" : "opacity-100 group-hover:opacity-0"}
                    `}>
                        <Pin className="size-3.5 text-[#5773B4] rotate-45" fill="#AEC9FF" />
                    </div>
                )}
                <DropdownMenu onOpenChange={setMenuOpen}>
                    <DropdownMenuTrigger asChild>
                        <button
                            className={`
                                absolute right-0 flex items-center justify-center p-1 rounded-md hover:bg-black/5 transition-opacity duration-200 outline-none
                                ${menuOpen ? "opacity-100 z-10" : "opacity-0 group-hover:opacity-100 z-10"}
                            `}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <MoreHorizontal className="size-4 text-[#4e5969]" />
                        </button>
                    </DropdownMenuTrigger>

                    <DropdownMenuContent
                        align="end"
                        sideOffset={8}
                        className="w-40 px-4 py-3 rounded-lg"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {type === "created" && <DropdownMenuItem
                            className="py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]"
                            onClick={() => onSettings?.(space)}
                        >
                            <Settings className="size-4 mr-2 text-[#4e5969]" />
                            <span className="">空间设置</span>
                        </DropdownMenuItem>}
                        {(type === "created" || space.role === SpaceRole.ADMIN) && (
                            <DropdownMenuItem className="py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]">
                                <Users className="size-4 mr-2 text-[#4e5969]" />
                                <span className="text-[14px] text-[#1d2129]">成员管理</span>
                            </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                            onClick={() => onPin(space.id, !space.isPinned)}
                            className="py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]"
                        >
                            {space.isPinned ? (
                                <><PinOff className="size-4 mr-2 text-[#4e5969]" /><span className="text-[14px] text-[#1d2129]">取消置顶</span></>
                            ) : (
                                <><Pin className="size-4 mr-2 text-[#4e5969]" /><span className="text-[14px] text-[#1d2129]">置顶知识空间</span></>
                            )}
                        </DropdownMenuItem>

                        <div className="h-px bg-[#f2f3f5] mx-2 my-1" />

                        <DropdownMenuItem
                            onClick={async () => {
                                const actionName = type === "created" ? "解散知识空间" : "退出知识空间";
                                const description = type === "created" ? "确认操作吗？" : "确定退出该知识空间吗？";
                                const ok = await confirm({
                                    title: "提示",
                                    description,
                                    confirmText: actionName === "解散知识空间" ? "删除" : "退出",
                                    cancelText: "取消"
                                })

                                if (ok) {
                                    type === "created" ? onDelete(space.id) : onLeave(space.id);
                                }
                            }}
                            className="text-[#f53f3f] py-2 px-0 cursor-pointer focus:bg-[#f2f3f5] focus:text-[#f53f3f]"
                        >
                            {type === "created" ? <MinimizeIcon className="size-4 mr-2" /> : <LogOut className="size-4 mr-2" />}
                            <span className="text-[14px] font-medium">{type === "created" ? "删除空间" : "退出空间"}</span>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
}
