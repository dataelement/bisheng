import {
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
import { useLocalize } from "~/hooks";
import { ChannelPinIcon } from "~/components/icons/channels";

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
                <div className={`flex-shrink-0 flex items-center justify-center size-5 rounded-md ${isActive ? "bg-white border border-[#165dff]/20 shadow-sm" : ""}`}>
                    <img
                        src={`${__APP_ENV__.BASE_URL}/assets/channel/notebook-one.svg`}
                        alt=""
                        className="size-3 object-contain shrink-0"
                        aria-hidden
                    />
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
                            <span className="">{localize("com_knowledge.space_settings")}</span>
                        </DropdownMenuItem>}
                        {(type === "created" || space.role === SpaceRole.ADMIN) && (
                            <DropdownMenuItem
                                className="py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]"
                                onClick={() => onManageMembers?.(space)}
                            >
                                <Users className="size-4 mr-2 text-[#4e5969]" />
                                <span className="text-[14px] text-[#1d2129]">{localize("com_knowledge.member_management")}</span>
                            </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                            onClick={() => onPin(space.id, !space.isPinned)}
                            className="py-2 px-0 cursor-pointer focus:bg-[#f2f3f5]"
                        >
                            {space.isPinned ? (
                                <><PinOff className="size-4 mr-2 text-[#4e5969]" /><span className="text-[14px] text-[#1d2129]">{localize("com_knowledge.unpin")}</span></>
                            ) : (
                                <><Pin className="size-4 mr-2 text-[#4e5969]" /><span className="text-[14px] text-[#1d2129]">{localize("com_knowledge.pin_space")}</span></>
                            )}
                        </DropdownMenuItem>

                        <div className="h-px bg-[#f2f3f5] mx-2 my-1" />

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
                            className="text-[#f53f3f] py-2 px-0 cursor-pointer focus:bg-[#f2f3f5] focus:text-[#f53f3f]"
                        >
                            {type === "created" ? <MinimizeIcon className="size-4 mr-2" /> : <LogOut className="size-4 mr-2" />}
                            <span className="text-[14px] font-medium">{type === "created" ? localize("com_knowledge.delete_space") : localize("com_knowledge.exit_space_short")}</span>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
}
