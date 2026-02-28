import {
    BlendIcon,
    MinimizeIcon,
    MoreHorizontal,
    Pin,
    PinOff,
    Settings,
    Users,
    X
} from "lucide-react";
import { useState } from "react";
import { Channel, ChannelRole } from "~/api/channels";
import { NotificationSeverity } from "~/common";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import { useConfirm, useToastContext } from "~/Providers";

interface ChannelItemProps {
    channel: Channel;
    isActive: boolean;
    type: "created" | "subscribed";
    onSelect: (channel: Channel) => void;
    onUpdate: (channel: Channel) => void;
    onDelete: (id: string) => void;
    onUnsubscribe: (id: string) => void;
    onPin: (id: string, pinned: boolean, type: "created" | "subscribed") => void;
}

export default function ChannelItem({
    channel,
    isActive,
    type,
    onSelect,
    onUpdate,
    onDelete,
    onUnsubscribe,
    onPin
}: ChannelItemProps) {
    const [isEditing, setIsEditing] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false); // 控制菜单打开时的状态显示
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
        if (newName && newName !== channel.name) {
            onUpdate({ ...channel, name: newName });
        }
    }

    return (
        <div
            className={`group flex items-center justify-between h-8 px-3 py-1.5 rounded-lg cursor-pointer transition-all border ${isActive
                ? "bg-[#E6EDFC] border-primary shadow-sm"
                : "border-transparent hover:bg-[#F7F7F7]"
                }`}
            onClick={() => !isEditing && onSelect(channel)}
        >
            <div className="flex items-center gap-1 flex-1 min-w-0">
                {/* 左侧图标保持不变 */}
                <div className={`flex-shrink-0 flex items-center justify-center size-5 rounded-md ${isActive ? "bg-white border border-[#165dff]/20 shadow-sm" : ""}`}>
                    <BlendIcon className={`size-3.5 ${isActive ? "text-[#165dff]" : "text-[#86909c]"}`} />
                </div>

                {isEditing ? (
                    <input
                        type="text"
                        defaultValue={channel.name}
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
                            {channel.name}
                        </span>
                        {channel.isPinned && (
                            <Pin className="size-3 text-[#5773B4] flex-shrink-0 rotate-45" fill="#AEC9FF" />
                        )}
                    </div>
                )}
            </div>

            {/* 右侧区域 */}
            <div className="flex items-center justify-end flex-shrink-0 w-8 h-5 relative">
                {/* 1. 徽标：非菜单打开 且 非Hover 时可见 */}
                {channel.unreadCount > 0 && (
                    <span className={`
                        absolute right-0 flex items-center justify-center
                        text-[10px] px-1.5 py-[1px] rounded-md font-medium bg-[#335CFF33]/20 text-primary
                        transition-opacity duration-200
                        ${menuOpen ? "opacity-0" : "group-hover:opacity-0"}
                    `}>
                        {channel.unreadCount}
                    </span>
                )}

                {/* 2. 操作按钮：菜单打开 或 Hover 时可见 */}
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
                        >
                            <Settings className="size-4 mr-2 text-[#4e5969]" />
                            <span className="">频道设置</span>
                        </DropdownMenuItem>}
                        {type === "created" || channel.role === ChannelRole.ADMIN && (
                            <>
                                <DropdownMenuItem className="py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]">
                                    <Users className="size-4 mr-2 text-[#4e5969]" />
                                    <span className="text-[14px] text-[#1d2129]">成员管理</span>
                                </DropdownMenuItem>
                            </>
                        )}
                        <DropdownMenuItem
                            onClick={() => onPin(channel.id, !channel.isPinned, type)}
                            className="py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]"
                        >
                            {channel.isPinned ? (
                                <><PinOff className="size-4 mr-2 text-[#4e5969]" /><span className="text-[14px] text-[#1d2129]">取消置顶</span></>
                            ) : (
                                <><Pin className="size-4 mr-2 text-[#4e5969]" /><span className="text-[14px] text-[#1d2129]">置顶频道</span></>
                            )}
                        </DropdownMenuItem>
                        <div className="h-px bg-[#f2f3f5] mx-2 my-1" />

                        <DropdownMenuItem
                            onClick={async () => {
                                const ok = await confirm({
                                    title: "提示",
                                    description: type === "created" ? "其他已订阅成员处的该频道也将被删除，确认操作吗？" : "确定取消对该频道及其子频道的订阅吗？",
                                    confirmText: "删除",
                                    cancelText: "确定"
                                })

                                if (ok) {
                                    console.log("执行删除逻辑...")
                                    type === "created" ? onDelete(channel.id) : onUnsubscribe(channel.id);
                                } else {
                                    console.log("用户取消了操作")
                                }
                            }}
                            className="text-[#f53f3f] py-2 px-0 cursor-pointer focus:bg-[#f2f3f5] focus:text-[#f53f3f]"
                        >
                            <MinimizeIcon className="size-4 mr-2" />
                            <span className="text-[14px] font-medium">{type === "created" ? "解散频道" : "取消订阅"}</span>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
}