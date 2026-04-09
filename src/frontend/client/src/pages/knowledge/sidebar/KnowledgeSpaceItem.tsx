import {
    MinimizeIcon,
    MoreHorizontal,
    Pin,
    PinOff,
    Settings,
    Users,
    LogOut,
} from "lucide-react";
import { useId, useState } from "react";
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
import { ChannelPinIcon } from "~/components/icons/channels";

function SpaceNotebookIcon({ active }: { active: boolean }) {
    const clipId = `nb-${useId().replace(/:/g, "")}`;
    return (
        <svg
            width={14}
            height={14}
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className={`size-3.5 shrink-0 ${active ? "text-[#165DFF]" : "text-[#818181]"}`}
            aria-hidden
        >
            <g clipPath={`url(#${clipId})`}>
                <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity={0.01} />
                <path
                    d="M2.66699 1.99998C2.66699 1.63179 2.96547 1.33331 3.33366 1.33331H12.667C13.0352 1.33331 13.3337 1.63179 13.3337 1.99998V14C13.3337 14.3682 13.0352 14.6666 12.667 14.6666H3.33366C2.96547 14.6666 2.66699 14.3682 2.66699 14V1.99998Z"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinejoin="round"
                />
                <path
                    d="M5.33301 1.33331V14.6666"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
                <path d="M8 4H10.6667" stroke="currentColor" strokeWidth={1.33333} strokeLinecap="round" strokeLinejoin="round" />
                <path
                    d="M8 6.66669H10.6667"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
                <path
                    d="M3.33301 1.33331H7.33301"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
                <path
                    d="M3.33301 14.6667H7.33301"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
            </g>
            <defs>
                <clipPath id={clipId}>
                    <rect width={16} height={16} fill="white" />
                </clipPath>
            </defs>
        </svg>
    );
}

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
        if (newName.length > 20) {
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
                    <SpaceNotebookIcon active={isActive} />
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
                        {type === "created" && (
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
                        {(type === "created" || space.role === SpaceRole.ADMIN) && (
                            <DropdownMenuItem
                                className={sidebarListMoreMenuItemClassName}
                                onClick={() => onManageMembers?.(space)}
                            >
                                <Users className={sidebarListMoreMenuIconClassName} />
                                <span className={sidebarListMoreMenuLabelClassName}>
                                    {localize("com_knowledge.member_management")}
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
                                <MinimizeIcon className={sidebarListMoreMenuDangerIconClassName} />
                            ) : (
                                <LogOut className={sidebarListMoreMenuDangerIconClassName} />
                            )}
                            <span className={sidebarListMoreMenuDangerLabelClassName}>
                                {type === "created" ? localize("com_knowledge.delete_space") : localize("com_knowledge.exit_space_short")}
                            </span>
                        </DropdownMenuItem>
                    </SidebarListMoreMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
}
