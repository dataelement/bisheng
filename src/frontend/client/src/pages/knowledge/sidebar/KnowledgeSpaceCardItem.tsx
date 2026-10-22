import { Outlined } from "bisheng-icons";
import { useState } from "react";
import { KnowledgeSpace } from "~/api/knowledge";
import { KnowledgeSpaceIcon } from "~/components/illustrations";
import { Dropdown, DropdownItem, DropdownSeparator } from "@bisheng/ui";
import { ActionMenuLoadingRow } from "~/components/ActionMenu";
import { useConfirm, useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import { formatTimeCard } from "../knowledgeUtils";

interface KnowledgeSpaceCardItemProps {
    space: KnowledgeSpace;
    isActive: boolean;
    type: "created" | "joined" | "department";
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
    const { showToast } = useToastContext();
    const confirm = useConfirm();

    // Action-menu items. While permissions are still resolving, show a single
    // loading row so the menu doesn't open with one item and then grow to three.
    const moreMenuItems = permissionsLoading ? (
        <ActionMenuLoadingRow />
    ) : (
        <>
            {(canEditSpace || canManageMembers) && (
                <DropdownItem icon={<Outlined.Edit />} onSelect={() => onSettings?.(space)}>
                    {localize("com_knowledge.space_settings")}
                </DropdownItem>
            )}
            <DropdownItem
                icon={space.isPinned ? <Outlined.PinOff /> : <Outlined.Pin />}
                onSelect={() => onPin(space.id, !space.isPinned)}
            >
                {space.isPinned ? localize("com_knowledge.unpin") : localize("com_knowledge.pin_space")}
            </DropdownItem>

            {(canDeleteSpace || type === "joined") && (
                <>
                    <DropdownSeparator />
                    <DropdownItem
                        danger
                        icon={canDeleteSpace ? <Outlined.Delete /> : <Outlined.LogOut />}
                        onSelect={async () => {
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
                    >
                        {canDeleteSpace ? localize("com_knowledge.delete_space") : localize("com_knowledge.exit_space_short")}
                    </DropdownItem>
                </>
            )}
        </>
    );

    return (
        <div
            className={`group flex cursor-pointer items-center gap-2 rounded-lg py-3 transition-colors ${isActive ? "bg-[#EEEEEE]" : "active:bg-[#F4F4F4] fine-pointer:hover:bg-[#F4F4F4]"
                }`}
            onClick={() => onSelect(space)}
        >
            <KnowledgeSpaceIcon className="size-12 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1">
                    <span className="truncate text-sm leading-6 text-text-1">{space.name}</span>
                    {space.isPinned ? (
                        <Outlined.Pin className="size-3.5 shrink-0 text-text-3" aria-hidden />
                    ) : null}
                </div>
                {space.updatedAt && (
                    <div className="mt-1 truncate text-[12px] leading-4 text-text-3 tabular-nums">
                        {formatTimeCard(space.updatedAt)}
                    </div>
                )}
            </div>

            {/* The menu is portaled, but React events still bubble to the row's onClick. */}
            <span className="contents" onClick={(e) => e.stopPropagation()}>
                <Dropdown
                    align="end"
                    onOpenChange={(open) => { setMenuOpen(open); if (open) onMenuOpen?.(); }}
                    menu={moreMenuItems}
                >
                    <button
                        type="button"
                        aria-label={localize("com_knowledge.space_settings")}
                        className={`flex size-7 shrink-0 items-center justify-center rounded-md text-text-3 outline-none ${menuOpen ? "bg-[#E4E4E4]" : "active:bg-[#E4E4E4]"
                            }`}
                    >
                        <Outlined.More className="size-5" />
                    </button>
                </Dropdown>
            </span>
        </div>
    );
}
