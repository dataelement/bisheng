import { Outlined } from "bisheng-icons";
import { KnowledgeSpace } from "~/api/knowledge";
import { DropdownItem, DropdownSub, DropdownSeparator } from "@bisheng/ui";
import { useLocalize } from "~/hooks";

export interface SpaceActionMenuItemsProps {
    space: KnowledgeSpace;
    /** Adds the ⓘ summary as the first row. The breadcrumb's menu carries it;
     *  the header's settings button, which is about changing the space, does not. */
    showInfo?: boolean;
    onOpenSettings?: () => void;
    onDeleteSpace?: () => void;
    onLeaveSpace?: () => void;
    canEditSpace?: boolean;
    canManageMembers?: boolean;
    canDeleteSpace?: boolean;
    canLeaveSpace?: boolean;
}

/**
 * Which rows a given user actually gets. Exported so a trigger can hide itself
 * rather than open an empty menu — the gating lives here, next to the rows it
 * gates, instead of being restated at each call site.
 */
export function getSpaceActionFlags({
    onOpenSettings,
    onDeleteSpace,
    onLeaveSpace,
    canEditSpace = false,
    canManageMembers = false,
    canDeleteSpace = false,
    canLeaveSpace = false,
}: SpaceActionMenuItemsProps) {
    const showSettings = (canEditSpace || canManageMembers) && !!onOpenSettings;
    const showDelete = canDeleteSpace && !!onDeleteSpace;
    // Leaving is the joined-space counterpart of deleting, never both at once.
    const showLeave = !showDelete && canLeaveSpace && !!onLeaveSpace;
    return { showSettings, showDelete, showLeave, hasAny: showSettings || showDelete || showLeave };
}

/**
 * The space's own actions, as menu rows. Shared by the breadcrumb anchor's ▾ and
 * the header's settings button so the two can never drift apart.
 */
export function SpaceActionMenuItems(props: SpaceActionMenuItemsProps) {
    const localize = useLocalize();
    const { space, showInfo = false, onOpenSettings, onDeleteSpace, onLeaveSpace } = props;
    const { showSettings, showDelete, showLeave } = getSpaceActionFlags(props);

    return (
        <>
            {showInfo && (
                <DropdownSub icon={<Outlined.Info />} label={localize("com_knowledge.space_info")}>
<div className="space-y-1.5 text-sm text-text-1">
                            <div>
                                <span className="text-text-3">{localize("com_knowledge.space_desc_label")}</span>
                                <p className="break-words">{space.description || "-"}</p>
                            </div>
                            <div>
                                <span className="text-text-3">{localize("com_knowledge.creator_label")}</span>
                                <p className="break-words">{space.creator}</p>
                            </div>
                            <div>
                                <span className="text-text-3">{localize("com_knowledge.joined_count_label")}</span>
                                <p>{space.memberCount || 0}</p>
                            </div>
                            <div>
                                <span className="text-text-3">{localize("com_knowledge.total_files_label")}</span>
                                <p>{space.totalFileCount || 0}</p>
                            </div>
                        </div>

                </DropdownSub>
            )}
            {showSettings && (
                <DropdownItem
                    onSelect={onOpenSettings}
                    icon={<Outlined.Edit />}

                >{localize("com_knowledge.space_settings")}</DropdownItem>
            )}
            {(showDelete || showLeave) && <DropdownSeparator />}
            {showDelete && (
                <DropdownItem
                    danger
                    onSelect={onDeleteSpace}
                    icon={<Outlined.Delete />}

                >{localize("com_knowledge.delete_space")}</DropdownItem>
            )}
            {showLeave && (
                <DropdownItem
                    danger
                    onSelect={onLeaveSpace}
                    icon={<Outlined.LogOut />}

                >{localize("com_knowledge.exit_space_short")}</DropdownItem>
            )}
        </>
    );
}
