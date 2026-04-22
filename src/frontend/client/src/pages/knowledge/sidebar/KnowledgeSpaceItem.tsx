import { Building2, MoreHorizontal, Pin, PinOff, Settings, Share2, LogOut } from "lucide-react";
import { useState } from "react";
import { KnowledgeSpace, SpaceRole } from "~/api/knowledge";
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
import { useLocalize } from "~/hooks";
import { getFullWidthLength } from "~/utils";
import { ChannelPinIcon } from "~/components/icons/channels";
import ClosedIcon from "~/components/ui/icon/ClosedIcon";
import { SpaceNotebookIcon } from "~/components/icons/SpaceNotebookIcon";

interface KnowledgeSpaceItemProps {
    space: KnowledgeSpace;
    isActive: boolean;
    type: "created" | "joined" | "department";
    onSelect: (space: KnowledgeSpace) => void;
    onUpdate: (space: KnowledgeSpace) => void;
    onDelete: (id: string) => void;
    onLeave: (id: string) => void;
    onPin: (id: string, pinned: boolean) => void;
    onSettings?: (space: KnowledgeSpace) => void;
    onManageMembers?: (space: KnowledgeSpace) => void;
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
    onManageMembers,
}: KnowledgeSpaceItemProps) {
    const localize = useLocalize();
    const [isEditing, setIsEditing] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const { showToast } = useToastContext();
    const confirm = useConfirm()

    const rename = (e) => {
        const newName = e.target.value.trim();
        setIsEditing(false);
        if (!newName) return
        if (getFullWidthLength(newName) > 20) {
            return showToast({
                message: localize("com_knowledge.max_20_chars_spaced"),
                severity: NotificationSeverity.ERROR
            });
        }
        if (newName && newName !== space.name) {
            onUpdate({ ...space, name: newName });
        }
    }

    return (
        <div
            className={`group flex items-center justify-between h-8 px-3 py-1.5 rounded-lg cursor-pointer  border ${isActive
                ? "bg-[#E6EDFC] border-primary shadow-sm"
                : "border-transparent hover:bg-[#F7F7F7]"
                }`}
            style={{
                transitionProperty: 'background-color',
                transitionDuration: '350ms',
                transitionTimingFunction: 'ease-in-out'
            }}
            onClick={() => !isEditing && onSelect(space)}
        >
            <div className="flex items-center gap-1 flex-1 min-w-0">
                <div className={`flex-shrink-0 flex items-center justify-center size-5 rounded-md ${isActive ? "bg-white" : ""}`}>
                    {type === "department" ? (
                        <Building2 className={`size-[14px] ${isActive ? "text-primary" : "text-[#86909C]"}`} />
                    ) : (
                        <SpaceNotebookIcon active={isActive} />
                    )}
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
                    <div className="flex flex-1 min-w-0 items-center gap-1">
                        <span onDoubleClick={() => setIsEditing(true)} className="truncate text-[14px] text-[#1d2129]">
                            {space.name}
                        </span>
                        {space.isPinned && (
                            <ChannelPinIcon className="h-[14px] w-[14px] shrink-0" aria-hidden />
                        )}
                    </div>
                )}
            </div>

            <div className="relative flex h-5 w-8 flex-shrink-0 items-center justify-end">
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

                    <SidebarListMoreMenuContent onClick={(e) => e.stopPropagation()}>
                        {(type === "created" || type === "department") && (
                            <DropdownMenuItem
                                className={sidebarListMoreMenuItemClassName}
                                onClick={() => onSettings?.(space)}
                            >
                                <Settings className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>
                                    {localize("com_knowledge.space_settings")}
                                </span>
                            </DropdownMenuItem>
                        )}
                        {(type === "created" || type === "department" || space.role === SpaceRole.ADMIN) && (
                            <DropdownMenuItem
                                className={sidebarListMoreMenuItemClassName}
                                onClick={() => onManageMembers?.(space)}
                            >
                                <Share2 className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>
                                    {localize("com_knowledge.share")}
                                </span>
                            </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                            onClick={() => onPin(space.id, !space.isPinned)}
                            className={sidebarListMoreMenuItemClassName}
                        >
                            {space.isPinned ? (
                                <>
                                    <PinOff className={sidebarListMoreMenuIconClassName} />
                                    <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.unpin")}</span>
                                </>
                            ) : (
                                <>
                                    <Pin className={sidebarListMoreMenuIconClassName} />
                                    <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.pin_space")}</span>
                                </>
                            )}
                        </DropdownMenuItem>

                        <SidebarListMoreMenuDivider />

                        {type !== "department" && (
                            <DropdownMenuItem
                                onClick={async () => {
                                    const actionName = type === "created" ? localize("com_knowledge.dissolve_space") : localize("com_knowledge.exit_space");
                                    const description = type === "created" ? localize("com_knowledge.confirm_operation") : localize("com_knowledge.confirm_exit_space");
                                    const ok = await confirm({
                                        title: localize("com_knowledge.prompt"),
                                        description,
                                        confirmText: actionName === localize("com_knowledge.dissolve_space") ? localize("com_knowledge.delete") : localize("com_knowledge.exit"),
                                        cancelText: localize("com_knowledge.cancel")
                                    })

                                    if (ok) {
                                        type === "created" ? onDelete(space.id) : onLeave(space.id);
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
                                    {type === "created" ? localize("com_knowledge.delete_space") : localize("com_knowledge.exit_space_short")}
                                </span>
                            </DropdownMenuItem>
                        )}
                        {type === "department" && space.role === SpaceRole.CREATOR && (
                            <DropdownMenuItem
                                onClick={async () => {
                                    const ok = await confirm({
                                        title: localize("com_knowledge.prompt"),
                                        description: localize("com_knowledge.confirm_operation"),
                                        confirmText: localize("com_knowledge.delete"),
                                        cancelText: localize("com_knowledge.cancel")
                                    })
                                    if (ok) onDelete(space.id);
                                }}
                                className={sidebarListMoreMenuDangerItemClassName}
                            >
                                <ClosedIcon className={sidebarListMoreMenuDangerIconClassName} />
                                <span className={sidebarListMoreMenuDangerLabelClassName}>
                                    {localize("com_knowledge.delete_space")}
                                </span>
                            </DropdownMenuItem>
                        )}
                    </SidebarListMoreMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
}
