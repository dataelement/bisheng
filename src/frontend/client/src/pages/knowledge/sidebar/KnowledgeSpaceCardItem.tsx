import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { KnowledgeSpace } from "~/api/knowledge";
import { KnowledgeSpaceIcon } from "~/components/illustrations";
import {
    DropdownMenu,
    DropdownMenuItem,
    DropdownMenuTrigger,
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

interface KnowledgeSpaceCardItemProps {
    space: KnowledgeSpace;
    isActive: boolean;
    type: "created" | "joined" | "department";
    onSelect: (space: KnowledgeSpace) => void;
    onDelete: (id: string) => void;
    onLeave: (id: string) => void;
    onPin: (id: string, pinned: boolean) => void;
    onSettings?: (space: KnowledgeSpace) => void;
    onManageMembers?: (space: KnowledgeSpace) => void;
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
    onSelect,
    onDelete,
    onLeave,
    onPin,
    onSettings,
    onManageMembers,
    canEditSpace = false,
    canDeleteSpace = false,
    canManageMembers = false,
}: KnowledgeSpaceCardItemProps) {
    const localize = useLocalize();
    const [menuOpen, setMenuOpen] = useState(false);
    const { showToast } = useToastContext();
    const confirm = useConfirm();

    const itemCount = space.totalFileCount ?? space.fileCount ?? 0;

    return (
        <div
            className={`group flex cursor-pointer items-center gap-2 rounded-lg py-3 transition-colors ${isActive ? "bg-[#EEEEEE]" : "active:bg-[#F4F4F4] fine-pointer:hover:bg-[#F4F4F4]"
                }`}
            onClick={() => onSelect(space)}
        >
            <KnowledgeSpaceIcon className="size-12 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1">
                    <span className="truncate text-sm leading-6 text-[#212121]">{space.name}</span>
                    {space.isPinned ? (
                        <Outlined.Pin className="size-3.5 shrink-0 text-[#86909C]" aria-hidden />
                    ) : null}
                </div>
                <div className="mt-1 truncate text-[12px] leading-4 text-[#86909C]">
                    {localize("com_knowledge_items_count", { count: itemCount })}
                </div>
            </div>

            <DropdownMenu onOpenChange={setMenuOpen}>
                <DropdownMenuTrigger asChild>
                    <button
                        type="button"
                        aria-label={localize("com_knowledge.space_settings")}
                        className={`flex size-7 shrink-0 items-center justify-center rounded-md text-[#999] outline-none ${menuOpen ? "bg-[#E4E4E4]" : "active:bg-[#E4E4E4]"
                            }`}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <Outlined.More className="size-5" />
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
                </SidebarListMoreMenuContent>
            </DropdownMenu>
        </div>
    );
}
