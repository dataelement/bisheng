import { Building2, ChevronDown, ChevronRight, LogOut, MoreHorizontal, Pin, PinOff, Settings, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { KnowledgeSpace, SpaceLevel, SpaceRole, SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED } from "~/api/knowledge";
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
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { getFullWidthLength } from "~/utils";
import { ChannelPinIcon } from "~/components/icons/channels";
import ClosedIcon from "~/components/ui/icon/ClosedIcon";
import { SpaceNotebookIcon } from "~/components/icons/SpaceNotebookIcon";
import { KnowledgeFolderTree, type FolderSelectPayload } from "./KnowledgeFolderTree";
import { isFavoriteSpace } from "../portal/favoriteView";

interface KnowledgeSpaceItemProps {
    space: KnowledgeSpace;
    isActive: boolean;
    type: SpaceLevel;
    onSelect: (space: KnowledgeSpace) => void;
    onUpdate: (space: KnowledgeSpace) => void;
    onDelete: (id: string) => void;
    onLeave: (id: string) => void;
    onPin: (id: string, pinned: boolean) => void;
    onSettings?: (space: KnowledgeSpace) => void;
    onManageMembers?: (space: KnowledgeSpace) => void;
    canEditSpace?: boolean;
    canDeleteSpace?: boolean;
    canManageMembers?: boolean;
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
    canEditSpace = false,
    canDeleteSpace = false,
    canManageMembers = false,
}: KnowledgeSpaceItemProps) {
    const localize = useLocalize();
    const [isEditing, setIsEditing] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [expanded, setExpanded] = useState(isActive);
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const navigate = useNavigate();
    const { spaceId, folderId: urlFolderId } = useParams<{ spaceId?: string; folderId?: string }>();
    const showDangerAction = canDeleteSpace || Boolean(space.canUnsubscribe);
    // 『我的收藏』为系统知识库：只可查看/取消收藏，不提供设置、置顶、删除、重命名等任何操作
    const isFavorite = isFavoriteSpace(space);

    const { data: bsConfig } = useGetBsConfig();
    const treeEnabled =
        bsConfig?.knowledge_space?.tree_structured_directory_display ?? true;

    useEffect(() => {
        if (isActive) setExpanded(true);
    }, [isActive]);

    const handleSelectFolder = (folder: FolderSelectPayload | null) => {
        if (folder) {
            navigate(`/knowledge/space/${space.id}/folder/${folder.id}`);
        } else {
            navigate(`/knowledge/space/${space.id}`);
        }
    };

    const rename = (e: React.FocusEvent<HTMLInputElement>) => {
        const newName = e.target.value.trim();
        setIsEditing(false);
        if (!newName) return;
        if (getFullWidthLength(newName) > 20) {
            return showToast({
                message: localize("com_knowledge.max_20_chars_spaced"),
                severity: NotificationSeverity.ERROR
            });
        }
        if (newName && newName !== space.name) {
            onUpdate({ ...space, name: newName });
        }
    };

    return (
        <div>
            <div
                className={`group flex items-center justify-between h-8 px-3 py-1.5 rounded-lg cursor-pointer border ${isActive
                    ? "bg-[#E6EDFC] border-primary shadow-sm"
                    : "border-transparent hover:bg-[#F7F7F7]"
                    }`}
                style={{
                    transitionProperty: "background-color",
                    transitionDuration: "350ms",
                    transitionTimingFunction: "ease-in-out"
                }}
                onClick={() => !isEditing && onSelect(space)}
            >
                <div className="flex items-center gap-1 flex-1 min-w-0">
                    {treeEnabled && (
                        <button
                            type="button"
                            className="flex size-4 shrink-0 items-center justify-center rounded transition-colors hover:bg-black/10"
                            onClick={(e) => {
                                e.stopPropagation();
                                setExpanded((prev) => !prev);
                            }}
                            aria-label={expanded ? "Collapse folder tree" : "Expand folder tree"}
                        >
                            {expanded ? (
                                <ChevronDown className="size-3 text-[#8D93A0]" />
                            ) : (
                                <ChevronRight className="size-3 text-[#8D93A0]" />
                            )}
                        </button>
                    )}

                    <div className={`flex-shrink-0 flex items-center justify-center size-5 rounded-md ${isActive ? "bg-white" : ""}`}>
                        {type === SpaceLevel.DEPARTMENT ? (
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
                            <span onDoubleClick={() => canEditSpace && !isFavorite && setIsEditing(true)} className="truncate text-[14px] text-[#1d2129]">
                                {space.name}
                            </span>
                            {space.isPinned && (
                                <ChannelPinIcon className="h-[14px] w-[14px] shrink-0" aria-hidden />
                            )}
                        </div>
                    )}
                </div>

                {!isFavorite && (
                <div className="relative flex h-5 w-8 flex-shrink-0 items-center justify-end">
                    <DropdownMenu onOpenChange={setMenuOpen}>
                        <DropdownMenuTrigger asChild>
                            <button
                                className={`
                                    absolute right-0 flex items-center justify-center p-1 rounded-md hover:bg-black/5 transition-opacity duration-200 outline-none
                                    ${menuOpen ? "opacity-100 z-10" : "coarse-pointer:opacity-100 fine-pointer:opacity-0 fine-pointer:group-hover:opacity-100 z-10"}
                                `}
                                onClick={(e) => e.stopPropagation()}
                            >
                                <MoreHorizontal className="size-4 text-[#4e5969]" />
                            </button>
                        </DropdownMenuTrigger>

                        <SidebarListMoreMenuContent onClick={(e) => e.stopPropagation()}>
                            {canEditSpace && (
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
                            {canManageMembers && (
                                <DropdownMenuItem
                                    className={sidebarListMoreMenuItemClassName}
                                    onClick={() => onManageMembers?.(space)}
                                >
                                    <UsersRound className={sidebarListMoreMenuIconClassName} />
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

                            {showDangerAction && (
                                <DropdownMenuItem
                                    onClick={async () => {
                                        const description = canDeleteSpace ? localize("com_knowledge.confirm_operation") : localize("com_knowledge.confirm_exit_space");
                                        const ok = await confirm({
                                            title: localize("com_knowledge.prompt"),
                                            description,
                                            confirmText: canDeleteSpace ? localize("com_knowledge.delete") : localize("com_knowledge.exit"),
                                            cancelText: localize("com_knowledge.cancel")
                                        });

                                        if (ok) {
                                            canDeleteSpace ? onDelete(space.id) : onLeave(space.id);
                                        }
                                    }}
                                    className={sidebarListMoreMenuDangerItemClassName}
                                >
                                    {canDeleteSpace ? (
                                        <ClosedIcon className={sidebarListMoreMenuDangerIconClassName} />
                                    ) : (
                                        <LogOut className={sidebarListMoreMenuDangerIconClassName} />
                                    )}
                                    <span className={sidebarListMoreMenuDangerLabelClassName}>
                                        {canDeleteSpace ? localize("com_knowledge.delete_space") : localize("com_knowledge.exit_space_short")}
                                    </span>
                                </DropdownMenuItem>
                            )}
                        </SidebarListMoreMenuContent>
                    </DropdownMenu>
                </div>
                )}
            </div>

            {expanded && treeEnabled && (
                <div className="pl-7">
                    <KnowledgeFolderTree
                        knowledgeId={space.id}
                        currentFolderId={urlFolderId && spaceId === space.id ? urlFolderId : undefined}
                        fileStatus={
                            space.role === SpaceRole.MEMBER
                                ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED
                                : undefined
                        }
                        onSelectFolder={handleSelectFolder}
                    />
                </div>
            )}
        </div>
    );
}
