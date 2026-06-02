import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { KnowledgeSpace, SpaceRole, SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import {
    DropdownMenu,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import {
    SidebarListMoreMenuContent,
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
import { KnowledgeFolderTree, type FolderSelectPayload } from "./KnowledgeFolderTree";
import { DynamicEllipsisName } from "./DynamicEllipsisName";

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

    const { data: bsConfig } = useGetBsConfig();
    const treeEnabled =
        bsConfig?.knowledge_space?.tree_structured_directory_display ?? true;

    // Auto-expand when this space becomes active
    useEffect(() => {
        if (isActive) setExpanded(true);
    }, [isActive]);

    // Only highlight the space row when this space is active AND no folder
    // inside it is selected — folders take over the active styling once chosen
    // so only one row in the tree appears active at a time.
    const isFolderSelectedHere = isActive && !!urlFolderId;
    const showSpaceHighlight = isActive && !isFolderSelectedHere;

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
        <div className="flex flex-col gap-0.5">
            {/* Space row */}
            <div
                data-ee-row
                className={`group flex items-center justify-between h-7 rounded-md cursor-pointer border ${showSpaceHighlight
                    ? "bg-[#EEEEEE] border-transparent"
                    : "border-transparent hover:bg-[#F4F4F4]"
                    }`}
                style={{
                    transitionProperty: 'background-color',
                    transitionDuration: '350ms',
                    transitionTimingFunction: 'ease-in-out'
                }}
                onClick={() => !isEditing && onSelect(space)}
            >
                <div className="flex items-center flex-1">
                    {/* Expand/collapse chevron — only shown when treeEnabled */}
                    {treeEnabled && (
                        <button
                            type="button"
                            className="flex size-5 shrink-0 items-center justify-center"
                            onClick={(e) => {
                                e.stopPropagation();
                                setExpanded((prev) => !prev);
                            }}
                            aria-label={expanded ? "Collapse folder tree" : "Expand folder tree"}
                        >
                            {expanded ? (
                                <Outlined.Down className="size-4 text-[#8D93A0]" />
                            ) : (
                                <Outlined.Right className="size-4 text-[#8D93A0]" />
                            )}
                        </button>
                    )}

                    <div className="flex-shrink-0 flex items-center justify-center size-5 rounded-md">
                        {type === "department" ? (
                            <Outlined.City className={`size-4 ${showSpaceHighlight ? "text-[#1d2129]" : "text-[#86909C]"}`} />
                        ) : (
                            <Outlined.Notebook className={`size-4 ${showSpaceHighlight ? "text-[#1d2129]" : "text-[#86909C]"}`} />
                        )}
                    </div>

                    {isEditing ? (
                        <input
                            type="text"
                            defaultValue={space.name}
                            className="flex-1 px-1 min-w-0 text-[12px] leading-5 bg-white rounded focus:outline-none"
                            autoFocus
                            onBlur={rename}
                            onKeyDown={(e) => {
                                if (e.key === "Enter") e.currentTarget.blur();
                                else if (e.key === "Escape") setIsEditing(false);
                            }}
                            onClick={(e) => e.stopPropagation()}
                        />
                    ) : (
                        <DynamicEllipsisName
                            name={space.name}
                            onDoubleClick={() => canEditSpace && setIsEditing(true)}
                            textClassName={`text-[12px] leading-5 text-[#1d2129] ${showSpaceHighlight ? "font-semibold" : ""}`}
                            trailing={
                                space.isPinned ? (
                                    <Outlined.Pin className="size-3 shrink-0 text-[#86909C]" aria-hidden />
                                ) : null
                            }
                        />
                    )}
                </div>

                {/* More-menu trigger. The button reserves real layout width so the item name
                    ends *before* it — when an item is scrolled to its end the name's tail stays
                    fully visible instead of being hidden under the button. Only the 20px button
                    itself carries an opaque bg (matching the row state) to cover text it floats
                    over; the 12px right gap stays transparent.
                      • w-8 (32px border box) + pr-3 (12px) → 20px button + 12px transparent gap;
                        justify-start keeps the button on the left.
                      • sticky right-1 (4px): margin-box right edge sticks 4px from the viewport.
                      • -mr-3 (-12px): negative right margin lets the box extend past the list's
                        right padding so the button can reach its intended offset from the edge. */}
                <div className="sticky right-1 z-[1] ml-2 -mr-3 pr-3 flex h-5 w-8 flex-shrink-0 items-center justify-start">
                    <DropdownMenu onOpenChange={setMenuOpen}>
                        <DropdownMenuTrigger asChild>
                            <button
                                className={`
                                    flex size-5 items-center justify-center rounded-md outline-none
                                    ${showSpaceHighlight ? "bg-[#EEEEEE] hover:!bg-[#E4E4E4]" : "bg-[#FBFBFB] group-hover:bg-[#F4F4F4] hover:!bg-[#E4E4E4]"}
                                    ${menuOpen ? "opacity-100" : "coarse-pointer:opacity-100 fine-pointer:opacity-0 fine-pointer:group-hover:opacity-100"}
                                `}
                                // Match the row's background-color transition (350ms ease-in-out)
                                // so the button bg fades in sync with the row; keep opacity at 200ms.
                                style={{
                                    transitionProperty: "opacity, background-color",
                                    transitionDuration: "200ms, 350ms",
                                    transitionTimingFunction: "ease, ease-in-out",
                                }}
                                onClick={(e) => e.stopPropagation()}
                            >
                                <Outlined.More className="size-4 text-[#4e5969]" />
                            </button>
                        </DropdownMenuTrigger>

                        <SidebarListMoreMenuContent onClick={(e) => e.stopPropagation()}>
                            {canEditSpace && (
                                <DropdownMenuItem
                                    className={sidebarListMoreMenuItemClassName}
                                    onClick={() => onSettings?.(space)}
                                >
                                    <Outlined.Edit className={sidebarListMoreMenuIconClassName} />
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
                                    <Outlined.PeopleSafe className={sidebarListMoreMenuIconClassName} />
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
                                        <Outlined.PinOff className={sidebarListMoreMenuIconClassName} />
                                        <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.unpin")}</span>
                                    </>
                                ) : (
                                    <>
                                        <Outlined.Pin className={sidebarListMoreMenuIconClassName} />
                                        <span className={sidebarListMoreMenuLabelClassName}>{localize("com_knowledge.pin_space")}</span>
                                    </>
                                )}
                            </DropdownMenuItem>

                            {(canDeleteSpace || type === "joined") && (
                                <DropdownMenuItem
                                    onClick={async () => {
                                        const actionName = canDeleteSpace ? localize("com_knowledge.dissolve_space") : localize("com_knowledge.exit_space");
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
                                        <Outlined.Delete className={sidebarListMoreMenuDangerIconClassName} />
                                    ) : (
                                        <Outlined.LogOut className={sidebarListMoreMenuDangerIconClassName} />
                                    )}
                                    <span className={sidebarListMoreMenuDangerLabelClassName}>
                                        {canDeleteSpace ? localize("com_knowledge.delete_space") : localize("com_knowledge.exit_space_short")}
                                    </span>
                                </DropdownMenuItem>
                            )}
                        </SidebarListMoreMenuContent>
                    </DropdownMenu>
                </div>
            </div>

            {/* Folder tree — nested under this space row when expanded.
                No wrapper indent: each tree node uses its own paddingLeft
                ((depth+1)*20) so depth-0 folders align with the space row's
                icon position, matching the design's 20px-per-level structure. */}
            {expanded && treeEnabled && (
                <div>
                    <KnowledgeFolderTree
                        knowledgeId={space.id}
                        currentFolderId={urlFolderId && spaceId === space.id ? urlFolderId : undefined}
                        // Mirror the right-side panel: MEMBER-role users hide FAILED
                        // items, so the tree must apply the same status filter.
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
