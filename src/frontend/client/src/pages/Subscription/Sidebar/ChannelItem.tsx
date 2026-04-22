import { useLocalize } from "~/hooks";
import { LogOut, MoreHorizontal, Pin, PinOff, Settings, Share2 } from "lucide-react";
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
import { useConfirm, useToastContext } from "~/Providers";
import { cn, getFullWidthLength } from "~/utils";
import { ChannelPinIcon } from "~/components/icons/channels";
import ClosedIcon from "~/components/ui/icon/ClosedIcon";
import { SpaceNotebookIcon } from "~/components/icons/SpaceNotebookIcon";

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
        if (getFullWidthLength(newName) > 10) {
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
                <div className={`flex-shrink-0 flex items-center justify-center size-5 rounded-md ${isActive ? "bg-white" : ""}`}>
                    <SpaceNotebookIcon active={isActive} />
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

            {/* 右侧区域：窄屏为徽标在左/更多在右；宽屏为徽标与更多叠放。仅粗指针设备上更多按钮常驻，窄屏 PC 仍 hover 显示 */}
            <div
                className={cn(
                    "relative flex flex-shrink-0 items-center justify-end",
                    "touch-mobile:min-w-0 touch-mobile:gap-1.5 touch-mobile:pl-1",
                    "touch-desktop:h-5 touch-desktop:w-8",
                )}
            >
                {channel.unreadCount > 0 && (
                    <span
                        className={cn(
                            "flex items-center justify-center rounded-md bg-[#335CFF33]/20 px-1.5 py-[1px] text-[10px] font-medium text-primary",
                            "touch-mobile:relative touch-mobile:shrink-0 coarse-pointer:opacity-100",
                            "touch-desktop:absolute touch-desktop:right-0",
                            menuOpen
                                ? "opacity-0"
                                : "coarse-pointer:opacity-100 fine-pointer:group-hover:opacity-0",
                        )}
                        style={{
                            transitionProperty: "opacity, background-color",
                            transitionDuration: "350ms",
                            transitionTimingFunction: "ease-in-out",
                        }}
                    >
                        {channel.unreadCount}
                    </span>
                )}

                <DropdownMenu onOpenChange={setMenuOpen}>
                    <DropdownMenuTrigger asChild>
                        <button
                            type="button"
                            className={cn(
                                "z-10 flex size-7 shrink-0 items-center justify-center rounded-md outline-none hover:bg-black/5",
                                menuOpen && "opacity-100",
                                !menuOpen &&
                                    "coarse-pointer:opacity-100 fine-pointer:opacity-0 fine-pointer:group-hover:opacity-100",
                            )}
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
                                <Share2 className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>
                                    {localize("com_subscription.share")}
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
                            {type === "created" ? (
                                <ClosedIcon className={sidebarListMoreMenuDangerIconClassName} />
                            ) : (
                                <LogOut className={sidebarListMoreMenuDangerIconClassName} />
                            )}
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
