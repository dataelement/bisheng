import { useLocalize } from "~/hooks";
import {
    MoreHorizontal,
    Pin,
    PinOff,
    Settings,
    Users,
} from "lucide-react";
import { useState } from "react";
import { Channel, ChannelRole } from "~/api/channels";
import { NotificationSeverity } from "~/common";
import {
    DropdownMenu,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import {
    SidebarListMoreMenuContent,
    SidebarListMoreMenuDivider,
    sidebarListMoreMenuDangerIconClassName,
    sidebarListMoreMenuDangerItemClassName,
    sidebarListMoreMenuDangerLabelClassName,
    sidebarListMoreMenuIconClassName,
    sidebarListMoreMenuItemClassName,
    sidebarListMoreMenuLabelClassName,
} from "~/components/SidebarListMoreMenu";
import ClosedIcon from "~/components/ui/icon/ClosedIcon";
import { useConfirm, useToastContext } from "~/Providers";
import {
    ChannelApplicationIcon,
    ChannelAppeffectIcon,
    ChannelPinIcon,
} from "~/components/icons/channels";

interface ChannelItemProps {
    channel: Channel;
    isActive: boolean;
    type: "created" | "subscribed";
    onSelect: (channel: Channel) => void;
    onUpdate: (channel: Channel) => void;
    onDelete: (id: string) => void;
    onUnsubscribe: (id: string) => void;
    onPin: (id: string, pinned: boolean, type: "created" | "subscribed") => void;
    onManageMembers: (channel: Channel) => void;
    onChannelSettings: (channel: Channel) => void;
}

export default function ChannelItem({
    channel,
    isActive,
    type,
    onSelect,
    onUpdate,
    onDelete,
    onUnsubscribe,
    onPin,
    onManageMembers,
    onChannelSettings
}: ChannelItemProps) {
    const localize = useLocalize();
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
                message: localize("com_subscription.max_10_characters"),
                severity: NotificationSeverity.ERROR
            });
        }
        if (newName && newName !== channel.name) {
            onUpdate({ ...channel, name: newName });
        }
    }

    return (
        <div
            className={`group flex items-center justify-between h-8 px-3 py-1.5 rounded-lg cursor-pointer border ${isActive
                ? "bg-[#E6EDFC] border-primary shadow-sm"
                : "border-transparent hover:bg-[#F7F7F7]"
                }`}
            style={{
                transitionProperty: 'background-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out'
            }}
            onClick={() => !isEditing && onSelect(channel)}
        >
            <div className="flex items-center gap-1 flex-1 min-w-0">
                {/* 左侧图标保持不变 */}
                <div className={`flex-shrink-0 flex items-center justify-center size-5 rounded-md ${isActive ? "bg-white border border-[#165dff]/20 shadow-sm" : ""}`}>
                    {isActive ? (
                        <ChannelAppeffectIcon className="size-3.5" />
                    ) : (
                        <ChannelApplicationIcon className="size-3.5" />
                    )}
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
                        <span onDoubleClick={() => type === "created" && setIsEditing(true)} className="text-[14px] truncate text-[#1d2129]">
                            {channel.name}
                        </span>
                        {channel.isPinned && (
                            <ChannelPinIcon className="w-[14px] h-[14px] flex-shrink-0" />
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
                        ${menuOpen ? "opacity-0" : "group-hover:opacity-0"}
                    `}
                        style={{
                            transitionProperty: 'background-color',
                            transitionDuration: '350ms',
                            // transitionDelay: '100ms',
                            transitionTimingFunction: 'ease-in-out'
                        }}
                    >
                        {channel.unreadCount}
                    </span>
                )}

                {/* 2. 操作按钮：菜单打开 或 Hover 时可见 */}
                <DropdownMenu onOpenChange={setMenuOpen}>
                    <DropdownMenuTrigger asChild>
                        <button
                            className={`
                                absolute right-0 flex items-center justify-center p-1 rounded-md hover:bg-black/5 outline-none
                                ${menuOpen ? "opacity-100 z-10" : "opacity-0 group-hover:opacity-100 z-10"}
                            `}
                            onClick={(e) => e.stopPropagation()}
                        >
                            <MoreHorizontal className="size-4 text-[#4e5969]" />
                        </button>
                    </DropdownMenuTrigger>

                    <SidebarListMoreMenuContent onClick={(e) => e.stopPropagation()}>
                        {type === "created" && (
                            <DropdownMenuItem
                                className={sidebarListMoreMenuItemClassName}
                                onClick={() => onChannelSettings(channel)}
                            >
                                <Settings className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>
                                    {localize("com_subscription.channel_settings")}
                                </span>
                            </DropdownMenuItem>
                        )}
                        {[ChannelRole.CREATOR, ChannelRole.ADMIN].includes(channel.role) && (
                            <DropdownMenuItem
                                className={sidebarListMoreMenuItemClassName}
                                onClick={() => onManageMembers(channel)}
                            >
                                <Users className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>
                                    {localize("com_subscription.member_management")}
                                </span>
                            </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                            onClick={() => onPin(channel.id, !channel.isPinned, type)}
                            className={sidebarListMoreMenuItemClassName}
                        >
                            {channel.isPinned ? (
                                <>
                                    <PinOff className={sidebarListMoreMenuIconClassName} />
                                    <span className={sidebarListMoreMenuLabelClassName}>{localize("com_subscription.unpin")}</span>
                                </>
                            ) : (
                                <>
                                    <Pin className={sidebarListMoreMenuIconClassName} />
                                    <span className={sidebarListMoreMenuLabelClassName}>{localize("com_subscription.pin_channel")}</span>
                                </>
                            )}
                        </DropdownMenuItem>
                        <SidebarListMoreMenuDivider />

                        <DropdownMenuItem
                            onClick={async () => {
                                const ok = await confirm({
                                    title: localize("com_subscription.prompt_tip"),
                                    description: type === "created" ? localize("com_subscription.confirm_delete_channel_for_all") : localize("com_subscription.confirm_unsubscribe_channel_and_subs"),
                                    confirmText: localize("com_subscription.confirm"),
                                    cancelText: localize("com_subscription.cancel")
                                })

                                if (ok) {
                                    type === "created" ? onDelete(channel.id) : onUnsubscribe(channel.id);
                                }
                            }}
                            className={sidebarListMoreMenuDangerItemClassName}
                        >
                            <ClosedIcon className={sidebarListMoreMenuDangerIconClassName} />
                            <span className={sidebarListMoreMenuDangerLabelClassName}>
                                {type === "created" ? localize("com_subscription.dissolve_channel") : localize("com_subscription.unsubscribe")}
                            </span>
                        </DropdownMenuItem>
                    </SidebarListMoreMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
}