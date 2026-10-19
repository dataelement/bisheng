import { Breadcrumb, type BreadcrumbItem } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { KnowledgeSpace } from "~/api/knowledge";
import { DropdownMenu, DropdownMenuTrigger } from "~/components/ui/DropdownMenu";
import { ActionMenuContent } from "~/components/ActionMenu";
import { SpaceActionMenuItems } from "./SpaceActionMenuItems";
import { useLocalize } from "~/hooks";

interface SpaceBreadcrumbProps {
    space: KnowledgeSpace;
    /** Folder chain below the space root; empty while at the root itself. */
    currentPath: Array<{ id?: string; name: string }>;
    onNavigateFolder: (folderId?: string) => void;
    /** Opens space settings; the row is hidden when absent or not permitted. */
    onOpenSettings?: () => void;
    onDeleteSpace?: () => void;
    onLeaveSpace?: () => void;
    canEditSpace?: boolean;
    canManageMembers?: boolean;
    canDeleteSpace?: boolean;
    canLeaveSpace?: boolean;
}

/**
 * The header's location block: where you are, then the space action menu.
 *
 * Before this, the header swapped its <h1> from the space name to the current
 * folder name on drill-down, so both the "which space am I in" anchor and every
 * space-level action vanished below the root. The menu trigger now trails the
 * location at every depth — it took over the ⓘ icon's slot, and the summary that
 * icon used to hover open is its first row, so nothing was lost with it.
 * The path itself is `@bisheng/ui`'s Breadcrumb, so truncation, the collapse
 * past four levels and the narrow-screen thresholds are the component's rules,
 * not ours — including rendering nothing at the space root, where the chain is
 * one level and the <h1> says it already (组件-Breadcrumb面包屑.md §1).
 */
export function SpaceBreadcrumb({
    space,
    currentPath,
    onNavigateFolder,
    onOpenSettings,
    onDeleteSpace,
    onLeaveSpace,
    canEditSpace = false,
    canManageMembers = false,
    canDeleteSpace = false,
    canLeaveSpace = false,
}: SpaceBreadcrumbProps) {
    const localize = useLocalize();

    const isRoot = currentPath.length === 0;
    const items: BreadcrumbItem[] = [
        {
            key: "space",
            title: space.name,
            onClick: () => onNavigateFolder(undefined),
        },
        ...currentPath.map((folder, index) => ({
            key: folder.id ?? `folder-${index}`,
            title: folder.name,
            onClick: () => onNavigateFolder(folder.id),
        })),
    ];

    const spaceMenu = (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <button
                    type="button"
                    aria-label={localize("com_knowledge.space_actions")}
                    className="inline-flex size-6 shrink-0 items-center justify-center rounded text-text-3 outline-none transition-colors hover:bg-fill-2 hover:text-text-1 data-[state=open]:bg-fill-2 data-[state=open]:text-text-1"
                >
                    <Outlined.Down className="size-4" />
                </button>
            </DropdownMenuTrigger>
            <ActionMenuContent align="start" width={180}>
                <SpaceActionMenuItems
                    showInfo
                    space={space}
                    onOpenSettings={onOpenSettings}
                    onDeleteSpace={onDeleteSpace}
                    onLeaveSpace={onLeaveSpace}
                    canEditSpace={canEditSpace}
                    canManageMembers={canManageMembers}
                    canDeleteSpace={canDeleteSpace}
                    canLeaveSpace={canLeaveSpace}
                />
            </ActionMenuContent>
        </DropdownMenu>
    );

    /* The menu always trails the SPACE, never the folder you happen to be in:
       at the root that is the <h1> (the Breadcrumb renders nothing at one level,
       规范 §1); deeper in it is the chain's root level, so it goes into the
       component's rootTrailing slot rather than after the whole chain — hung off
       the tail it would read as the current folder's menu.

       gap-0.5, not gap-1: at the root the ▾ is spaced by THIS container, deeper
       in by the Breadcrumb's own 2px (规范 §3). Matching them is what keeps the
       trigger sitting identically against the space name at both levels. */
    return (
        <div className="flex min-w-0 flex-1 items-center gap-0.5">
            {isRoot ? (
                <>
                    <h1 className="min-w-0 truncate text-base leading-8 text-text-1">
                        {space.name}
                    </h1>
                    {spaceMenu}
                </>
            ) : (
                <Breadcrumb
                    items={items}
                    rootTrailing={spaceMenu}
                    // The trail doubles as this page's title, so it matches the
                    // root's <h1> (16/32) instead of the spec's default 12/24 —
                    // a local override, not a change to the shared default. The
                    // 96px parent cap is "about 8 CJK characters" at 12px, so it
                    // scales with the type or names would clip two characters early.
                    className="text-base leading-8"
                    parentMaxWidth={128}
                    ariaLabel={localize("com_knowledge.breadcrumb")}
                    expandLabel={(hiddenCount) =>
                        localize("com_knowledge.breadcrumb_expand_hidden", { 0: hiddenCount })
                    }
                />
            )}
        </div>
    );
}
