import { useState, useMemo } from "react";
import {
    Plus,
    Store,
    ChevronLeft,
    ChevronRight,
    ChevronDown,
    ArrowUpDown,
    Settings,
    Users,
    Trash2,
    Pin,
    PinOff
} from "lucide-react";
import { Button } from "~/components/ui/Button";
import { Channel, SortType, ChannelRole } from "~/api/channels";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";

interface ChannelSidebarProps {
    createdChannels: Channel[];
    subscribedChannels: Channel[];
    activeChannelId?: string;
    onChannelSelect: (channel: Channel) => void;
    onCreateChannel: () => void;
    onChannelSquare: () => void;
    onUpdateChannel: (channel: Channel) => void;
    onDeleteChannel: (channelId: string) => void;
    onUnsubscribeChannel: (channelId: string) => void;
    onPinChannel: (channelId: string, pinned: boolean) => void;
}

export function ChannelSidebar({
    createdChannels,
    subscribedChannels,
    activeChannelId,
    onChannelSelect,
    onCreateChannel,
    onChannelSquare,
    onUpdateChannel,
    onDeleteChannel,
    onUnsubscribeChannel,
    onPinChannel
}: ChannelSidebarProps) {
    const [collapsed, setCollapsed] = useState(false);
    const [createdCollapsed, setCreatedCollapsed] = useState(false);
    const [subscribedCollapsed, setSubscribedCollapsed] = useState(false);
    const [createdSortBy, setCreatedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [subscribedSortBy, setSubscribedSortBy] = useState<SortType>(SortType.RECENT_UPDATE);
    const [editingChannelId, setEditingChannelId] = useState<string | null>(null);
    const { showToast } = useToastContext();

    // 排序文本
    const getSortText = (sortType: SortType) => {
        switch (sortType) {
            case SortType.RECENT_UPDATE:
                return "最近更新";
            case SortType.RECENT_ADDED:
                return "最近添加";
            case SortType.NAME:
                return "频道名称";
        }
    };

    // 循环切换排序
    const toggleSort = (type: "created" | "subscribed") => {
        const sortTypes = [SortType.RECENT_UPDATE, SortType.RECENT_ADDED, SortType.NAME];
        const currentSort = type === "created" ? createdSortBy : subscribedSortBy;
        const currentIndex = sortTypes.indexOf(currentSort);
        const nextIndex = (currentIndex + 1) % sortTypes.length;
        const nextSort = sortTypes[nextIndex];

        if (type === "created") {
            setCreatedSortBy(nextSort);
        } else {
            setSubscribedSortBy(nextSort);
        }
    };

    // 置顶频道
    const handlePin = (channelId: string, pinned: boolean, type: "created" | "subscribed") => {
        const channels = type === "created" ? createdChannels : subscribedChannels;
        const pinnedCount = channels.filter(c => c.isPinned).length;

        if (pinned && pinnedCount >= 5) {
            showToast({
                message: "已达置顶数量限制",
                severity: NotificationSeverity.INFO
            });
            return;
        }

        onPinChannel(channelId, pinned);
    };

    // 渲染频道项
    const renderChannelItem = (channel: Channel, type: "created" | "subscribed") => {
        const isActive = channel.id === activeChannelId;
        const isEditing = editingChannelId === channel.id;

        return (
            <div
                key={channel.id}
                className={`group flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                    isActive ? "bg-[#e8f3ff] text-[#165dff]" : "hover:bg-[#f7f8fa]"
                }`}
                onClick={() => !isEditing && onChannelSelect(channel)}
            >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                    <span className="text-[#4e5969] flex-shrink-0">#</span>
                    {isEditing ? (
                        <input
                            type="text"
                            defaultValue={channel.name}
                            className="flex-1 px-2 py-1 text-[14px] border border-[#165dff] rounded focus:outline-none"
                            autoFocus
                            onBlur={(e) => {
                                const newName = e.target.value.trim();
                                if (newName && newName !== channel.name) {
                                    onUpdateChannel({ ...channel, name: newName });
                                }
                                setEditingChannelId(null);
                            }}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                    e.currentTarget.blur();
                                } else if (e.key === "Escape") {
                                    setEditingChannelId(null);
                                }
                            }}
                            onClick={(e) => e.stopPropagation()}
                        />
                    ) : (
                        <>
                            <span
                                className="flex-1 text-[14px] truncate"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    setEditingChannelId(channel.id);
                                }}
                            >
                                {channel.name}
                            </span>
                            {channel.isPinned && (
                                <Pin className="size-3 text-[#165dff] flex-shrink-0" fill="currentColor" />
                            )}
                        </>
                    )}
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                    {channel.unreadCount > 0 && (
                        <span className="bg-[#f53f3f] text-white text-[11px] px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
                            {channel.unreadCount}
                        </span>
                    )}

                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                className="opacity-0 group-hover:opacity-100 p-1 hover:bg-[#e5e6eb] rounded transition-opacity"
                                onClick={(e) => e.stopPropagation()}
                            >
                                <Settings className="size-4 text-[#4e5969]" />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40">
                            {channel.role === ChannelRole.CREATOR && (
                                <>
                                    <DropdownMenuItem onClick={() => onUpdateChannel(channel)}>
                                        <Settings className="size-4 mr-2" />
                                        频道设置
                                    </DropdownMenuItem>
                                    <DropdownMenuItem onClick={() => console.log("成员管理")}>
                                        <Users className="size-4 mr-2" />
                                        成员管理
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        onClick={() => {
                                            if (confirm("其他已订阅成员处的该频道也将被删除，确认操作吗？")) {
                                                onDeleteChannel(channel.id);
                                            }
                                        }}
                                        className="text-[#f53f3f]"
                                    >
                                        <Trash2 className="size-4 mr-2" />
                                        解散频道
                                    </DropdownMenuItem>
                                </>
                            )}

                            {channel.role === ChannelRole.ADMIN && type === "subscribed" && (
                                <>
                                    <DropdownMenuItem onClick={() => console.log("成员管理")}>
                                        <Users className="size-4 mr-2" />
                                        成员管理
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        onClick={() => {
                                            if (confirm("确定取消对该频道及其子频道的订阅吗？")) {
                                                onUnsubscribeChannel(channel.id);
                                            }
                                        }}
                                        className="text-[#f53f3f]"
                                    >
                                        <Trash2 className="size-4 mr-2" />
                                        取消订阅
                                    </DropdownMenuItem>
                                </>
                            )}

                            {channel.role === ChannelRole.MEMBER && type === "subscribed" && (
                                <DropdownMenuItem
                                    onClick={() => {
                                        if (confirm("确定取消对该频道及其子频道的订阅吗？")) {
                                            onUnsubscribeChannel(channel.id);
                                        }
                                    }}
                                    className="text-[#f53f3f]"
                                >
                                    <Trash2 className="size-4 mr-2" />
                                    取消订阅
                                </DropdownMenuItem>
                            )}

                            <DropdownMenuItem onClick={() => handlePin(channel.id, !channel.isPinned, type)}>
                                {channel.isPinned ? (
                                    <>
                                        <PinOff className="size-4 mr-2" />
                                        取消置顶
                                    </>
                                ) : (
                                    <>
                                        <Pin className="size-4 mr-2" />
                                        置顶
                                    </>
                                )}
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            </div>
        );
    };

    if (collapsed) {
        return (
            <div className="w-12 h-full bg-white border-r border-[#e5e6eb] flex items-start justify-center pt-4">
                <button
                    onClick={() => setCollapsed(false)}
                    className="p-2 hover:bg-[#f7f8fa] rounded transition-colors"
                >
                    <ChevronRight className="size-5 text-[#4e5969]" />
                </button>
            </div>
        );
    }

    return (
        <div className="w-64 h-full bg-white border-r border-[#e5e6eb] flex flex-col">
            {/* 顶部操作区 */}
            <div className="p-4 border-b border-[#e5e6eb] space-y-2">
                <div className="flex items-center gap-2">
                    <Button
                        onClick={onCreateChannel}
                        className="flex-1 h-8 text-[14px] bg-[#165dff] text-white hover:bg-[#4080ff]"
                    >
                        <Plus className="size-4 mr-1" />
                        创建频道
                    </Button>
                    <Button
                        onClick={onChannelSquare}
                        variant="outline"
                        className="flex-1 h-8 text-[14px] border-[#e5e6eb]"
                    >
                        <Store className="size-4 mr-1" />
                        频道广场
                    </Button>
                </div>
                <button
                    onClick={() => setCollapsed(true)}
                    className="w-full flex items-center justify-center p-1 hover:bg-[#f7f8fa] rounded transition-colors"
                >
                    <ChevronLeft className="size-4 text-[#4e5969]" />
                </button>
            </div>

            {/* 频道列表 */}
            <div className="flex-1 overflow-y-auto">
                {/* 我创建的 */}
                <div className="p-4">
                    <div className="flex items-center justify-between mb-2">
                        <button
                            onClick={() => setCreatedCollapsed(!createdCollapsed)}
                            className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]"
                        >
                            <ChevronDown
                                className={`size-3 transition-transform ${
                                    createdCollapsed ? "-rotate-90" : ""
                                }`}
                            />
                            我创建的
                        </button>
                        <button
                            onClick={() => toggleSort("created")}
                            className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]"
                        >
                            <ArrowUpDown className="size-3" />
                            {getSortText(createdSortBy)}
                        </button>
                    </div>

                    {!createdCollapsed && (
                        <div className="space-y-1">
                            {createdChannels.map((channel) => renderChannelItem(channel, "created"))}
                        </div>
                    )}
                </div>

                {/* 我关注的 */}
                <div className="p-4">
                    <div className="flex items-center justify-between mb-2">
                        <button
                            onClick={() => setSubscribedCollapsed(!subscribedCollapsed)}
                            className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]"
                        >
                            <ChevronDown
                                className={`size-3 transition-transform ${
                                    subscribedCollapsed ? "-rotate-90" : ""
                                }`}
                            />
                            我关注的
                        </button>
                        <button
                            onClick={() => toggleSort("subscribed")}
                            className="flex items-center gap-1 text-[12px] text-[#86909c] hover:text-[#4e5969]"
                        >
                            <ArrowUpDown className="size-3" />
                            {getSortText(subscribedSortBy)}
                        </button>
                    </div>

                    {!subscribedCollapsed && (
                        <div className="space-y-1">
                            {subscribedChannels.map((channel) => renderChannelItem(channel, "subscribed"))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
