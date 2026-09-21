import { Outlined } from "bisheng-icons";
import { useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { KnowledgeSpace } from "~/api/knowledge";
import { KnowledgeSpaceIcon } from "~/components/illustrations";
import {
    DropdownMenu,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { ActionMenuLoadingRow } from "~/components/ActionMenu";
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
import { cn } from "~/utils";
import { DemoTag } from "~/mock/demo/DemoTag";
import { formatTimeCard } from "../knowledgeUtils";
import { KnowledgeSpaceFolderArt } from "./KnowledgeSpaceFolderArt";

interface KnowledgeSpaceCardItemProps {
    space: KnowledgeSpace;
    isActive: boolean;
    type: "created" | "joined" | "department";
    /** Desktop home grid: a folder tile (name on the front cover) instead of a list row. */
    card?: boolean;
    onSelect: (space: KnowledgeSpace) => void;
    onDelete: (id: string) => void;
    onLeave: (id: string) => void;
    onPin: (id: string, pinned: boolean) => void;
    onSettings?: (space: KnowledgeSpace) => void;
    /** F040: lazily resolve this space's action permissions when its menu opens. */
    onMenuOpen?: () => void;
    /** True while the lazy permission lookup is in flight — the menu shows a
     *  loading row instead of the fail-closed item set so items don't pop in. */
    permissionsLoading?: boolean;
    canEditSpace?: boolean;
    canDeleteSpace?: boolean;
    canManageMembers?: boolean;
}

/**
 * Mobile full-page list row. Same data/actions as the desktop {@link KnowledgeSpaceItem}
 * (sort/create/pin/settings/members/delete come from the shared sidebar handlers),
 * only the presentation differs: large illustrated icon + name + item count, no folder tree.
 */
export default function KnowledgeSpaceCardItem({
    space,
    isActive,
    type,
    card = false,
    onSelect,
    onDelete,
    onLeave,
    onPin,
    onSettings,
    onMenuOpen,
    permissionsLoading = false,
    canEditSpace = false,
    canDeleteSpace = false,
    canManageMembers = false,
}: KnowledgeSpaceCardItemProps) {
    const localize = useLocalize();
    const [menuOpen, setMenuOpen] = useState(false);
    const [contextMenuOpen, setContextMenuOpen] = useState(false);
    const [contextMenuPosition, setContextMenuPosition] = useState({ x: 0, y: 0 });
    const { showToast } = useToastContext();
    const confirm = useConfirm();

    // Action-menu items. While permissions are still resolving, show a single
    // loading row so the menu doesn't open with one item and then grow to three.
    const moreMenuItems = permissionsLoading ? (
        <ActionMenuLoadingRow />
    ) : (
        <>
            {(canEditSpace || canManageMembers) && (
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
                        // Delete-space uses the destructive variant (matches file-delete).
                        // Exit-space keeps the default prompt — it's not destructive.
                        const ok = canDeleteSpace
                            ? await confirm({
                                description: `${localize("com_knowledge.confirm_delete_space")}${localize("com_knowledge.delete_irreversible_warning")}`,
                                variant: "destructive",
                            })
                            : await confirm({
                                title: localize("com_knowledge.prompt"),
                                description: localize("com_knowledge.confirm_exit_space"),
                                confirmText: localize("com_knowledge.exit"),
                                cancelText: localize("com_knowledge.cancel"),
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
        </>
    );

    const moreMenu = (
        <DropdownMenu onOpenChange={(open) => { setMenuOpen(open); if (open) onMenuOpen?.(); }}>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    aria-label={localize("com_knowledge.space_settings")}
                    className={cn(
                        "flex size-7 shrink-0 items-center justify-center rounded-md text-text-3 outline-none",
                        // Folder tile: pointer users get the hover arrow + right-click menu instead,
                        // so the trigger only exists on touch (no hover, no right click). It sits on
                        // the tinted front cover, hence the translucent pressed state rather than grey.
                        card
                            ? cn("hidden coarse-pointer:flex", menuOpen ? "bg-black/[0.06]" : "active:bg-black/[0.06]")
                            : menuOpen ? "bg-[#E4E4E4]" : "active:bg-[#E4E4E4]",
                    )}
                    onClick={(e) => e.stopPropagation()}
                >
                    <Outlined.More className="size-5" />
                </button>
            </DropdownMenuTrigger>

            <SidebarListMoreMenuContent onClick={(e) => e.stopPropagation()}>
                {moreMenuItems}
            </SidebarListMoreMenuContent>
        </DropdownMenu>
    );

    const nameRow = (
        <div className="flex items-center gap-1">
            <span className="truncate text-sm leading-6 text-text-1">{space.name}</span>
            <DemoTag id={space.id} className="shrink-0" />
            {space.isPinned ? (
                <Outlined.Pin className="size-3.5 shrink-0 text-text-3" aria-hidden />
            ) : null}
        </div>
    );

    const updatedAt = space.updatedAt ? (
        <div className={cn("truncate text-[12px] leading-4 text-text-3 tabular-nums", !card && "mt-1")}>
            {formatTimeCard(space.updatedAt)}
        </div>
    ) : null;

    const handleTileContextMenu = (e: MouseEvent<HTMLDivElement>) => {
        e.preventDefault();
        setContextMenuPosition({ x: e.clientX, y: e.clientY });
        setContextMenuOpen(true);
        onMenuOpen?.();
    };

    // Desktop home grid: folder tile — name / date sit on the folder's front cover. Hovering
    // reveals a plain "open" arrow; the space actions live on right click.
    if (card) {
        return (
            <div
                className="group cursor-pointer"
                onClick={() => onSelect(space)}
                onContextMenu={handleTileContextMenu}
            >
                {/* Right-click menu — same cursor-anchored invisible trigger as KnowledgeSpaceItem.
                    Portaled to <body>: the scroll container has `container-type: inline-size`,
                    which would otherwise become the fixed trigger's containing block. */}
                {createPortal(
                    <DropdownMenu open={contextMenuOpen} onOpenChange={setContextMenuOpen}>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                aria-hidden="true"
                                tabIndex={-1}
                                className="fixed size-0 opacity-0"
                                style={{ left: contextMenuPosition.x, top: contextMenuPosition.y }}
                                onClick={(e) => e.stopPropagation()}
                            />
                        </DropdownMenuTrigger>
                        <SidebarListMoreMenuContent onClick={(e) => e.stopPropagation()}>
                            {moreMenuItems}
                        </SidebarListMoreMenuContent>
                    </DropdownMenu>,
                    document.body,
                )}
                {/* No fileCount on purpose: the list endpoints only count files sitting in the
                    space ROOT (backend _populate_root_file_counts), so a space whose content
                    lives in sub-folders reports 0 and would wrongly render as an empty folder. */}
                <KnowledgeSpaceFolderArt tone={type}>
                    <div className="flex items-end gap-1">
                        <div className="min-w-0 flex-1">
                            {nameRow}
                            {updatedAt}
                        </div>
                        <Outlined.ArrowRight
                            className="mb-1 size-4 shrink-0 -translate-x-1 text-text-2 opacity-0 transition duration-200 group-hover:translate-x-0 group-hover:opacity-100 motion-reduce:transition-none coarse-pointer:hidden"
                            aria-hidden
                        />
                        {moreMenu}
                    </div>
                </KnowledgeSpaceFolderArt>
            </div>
        );
    }

    return (
        <div
            className={`group flex cursor-pointer items-center gap-2 rounded-lg py-3 transition-colors ${isActive ? "bg-[#EEEEEE]" : "active:bg-[#F4F4F4] fine-pointer:hover:bg-[#F4F4F4]"
                }`}
            onClick={() => onSelect(space)}
        >
            <KnowledgeSpaceIcon className="size-12 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
                {nameRow}
                {updatedAt}
            </div>
            {moreMenu}
        </div>
    );
}
