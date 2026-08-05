import { useState } from "react";
import { Outlined } from "bisheng-icons";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";

interface BreadcrumbNode {
    id?: string;
    name: string;
}

interface KnowledgeBreadcrumbProps {
    spaceName: string;
    /** Ancestor chain from root folder to the current folder (leaf last); space root NOT included. */
    currentPath: BreadcrumbNode[];
    onNavigateFolder: (folderId?: string) => void;
    className?: string;
}

/** Parent segment width cap: 8 CJK characters at 12px (design "最大长度为8个中文字符"). */
const PARENT_MAX_WIDTH = "max-w-[96px]";
/** When the chain exceeds 4 levels, collapse the middle into an ellipsis (spec §5.1). */
const COLLAPSE_THRESHOLD = 4;

function Separator() {
    return <Outlined.Right className="size-4 shrink-0 text-text-4" aria-hidden />;
}

/** Clickable parent segment: hover highlights with the brand color; long names truncate with a tooltip. */
function ParentCrumb({ node, onNavigate }: { node: BreadcrumbNode; onNavigate: (folderId?: string) => void }) {
    // The full-name tooltip only shows when the name actually overflows the width cap.
    const [overflowing, setOverflowing] = useState(false);

    const button = (
        <button
            type="button"
            onClick={() => onNavigate(node.id)}
            onMouseEnter={(e) => setOverflowing(e.currentTarget.scrollWidth > e.currentTarget.clientWidth)}
            className={cn(
                // text-text-3 is the client carrier of the `text-hint` role (gray-6, 色彩规范).
                "shrink-0 truncate text-text-3 transition-colors hover:text-blue-600",
                PARENT_MAX_WIDTH,
            )}
        >
            {node.name}
        </button>
    );

    return (
        <Tooltip>
            <TooltipTrigger asChild>{button}</TooltipTrigger>
            {overflowing && (
                <TooltipContent noArrow side="bottom" sideOffset={6} className="z-[999] max-w-[320px] break-all">
                    {node.name}
                </TooltipContent>
            )}
        </Tooltip>
    );
}

/**
 * Row inside the collapsed-levels menu: full name (no 96px cap — the user opened the menu
 * to read it), truncate + tooltip only past the menu's own 240px width cap (spec §5.3).
 */
function MenuItemName({ name }: { name: string }) {
    const [overflowing, setOverflowing] = useState(false);
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <span
                    className="min-w-0 flex-1 truncate"
                    onMouseEnter={(e) => setOverflowing(e.currentTarget.scrollWidth > e.currentTarget.clientWidth)}
                >
                    {name}
                </span>
            </TooltipTrigger>
            {/* Dark tooltip to the RIGHT of the menu panel so it never covers other rows. */}
            {overflowing && (
                <TooltipContent noArrow side="right" sideOffset={16} className="z-[999] max-w-[320px] break-all">
                    {name}
                </TooltipContent>
            )}
        </Tooltip>
    );
}

/**
 * Folder path breadcrumb above the knowledge-space header title (desktop only; design 2075:8134).
 * Hidden at the space root ("single level" case) — the caller only renders it inside a folder.
 * Collapse behavior follows 组件-Breadcrumb面包屑.md §5.
 */
export function KnowledgeBreadcrumb({ spaceName, currentPath, onNavigateFolder, className }: KnowledgeBreadcrumbProps) {
    const localize = useLocalize();
    // The ellipsis tooltip is fully controlled by pointer enter/leave. Radix's default
    // focus-open would re-show it (and leave it stuck) when the menu closes and returns
    // focus to the trigger.
    const [menuOpen, setMenuOpen] = useState(false);
    const [tipOpen, setTipOpen] = useState(false);
    // Full chain: space root first, current folder last.
    const items: BreadcrumbNode[] = [{ id: undefined, name: spaceName }, ...currentPath];
    const current = items[items.length - 1];
    const collapse = items.length > COLLAPSE_THRESHOLD;
    // Collapsed layout keeps the first item and the last two; the rest hide behind an ellipsis.
    const headParents = collapse ? [items[0]] : items.slice(0, -1);
    const hiddenParents = collapse ? items.slice(1, -2) : [];
    const tailParents = collapse ? [items[items.length - 2]] : [];

    return (
        <nav
            aria-label="breadcrumb"
            className={cn("flex min-w-0 items-center gap-0.5 text-caption leading-6 text-text-3", className)}
        >
            {headParents.map((node) => (
                <span key={node.id ?? "space-root"} className="flex shrink-0 items-center gap-0.5">
                    <ParentCrumb node={node} onNavigate={onNavigateFolder} />
                    <Separator />
                </span>
            ))}
            {collapse && (
                <span className="flex shrink-0 items-center gap-0.5">
                    {/* Spec §5.2/§5.3: the ellipsis is a discoverable button (24×24 gray container,
                        darker on hover and while the menu is open, tooltip says what it expands),
                        and it opens a click-to-open single-column menu — one level per row (top =
                        highest ancestor), no separators/indent, whole row clickable, scrolls past
                        8 rows. Radix provides Esc/outside-click close, arrow-key nav, aria-expanded. */}
                    <DropdownMenu
                        open={menuOpen}
                        onOpenChange={(open) => {
                            setMenuOpen(open);
                            if (open) setTipOpen(false);
                        }}
                    >
                        <Tooltip open={tipOpen}>
                            <TooltipTrigger asChild>
                                <DropdownMenuTrigger asChild>
                                    <button
                                        type="button"
                                        aria-label={localize("com_knowledge.breadcrumb_expand", { count: hiddenParents.length })}
                                        onMouseEnter={() => setTipOpen(!menuOpen)}
                                        onMouseLeave={() => setTipOpen(false)}
                                        className="flex size-6 shrink-0 cursor-pointer items-center justify-center rounded leading-none text-text-3 transition-colors hover:bg-fill-2 aria-expanded:bg-fill-2"
                                    >
                                        ...
                                    </button>
                                </DropdownMenuTrigger>
                            </TooltipTrigger>
                            {/* Mounted only while our controlled state says so — Radix's exit-animation
                                Presence can otherwise leave it stuck in the DOM after the menu closes. */}
                            {tipOpen && !menuOpen && (
                                <TooltipContent noArrow side="bottom" sideOffset={6} className="z-[999]">
                                    {localize("com_knowledge.breadcrumb_expand", { count: hiddenParents.length })}
                                </TooltipContent>
                            )}
                        </Tooltip>
                        <DropdownMenuContent
                            align="center"
                            sideOffset={4}
                            className="max-h-80 min-w-[120px] max-w-[240px] overflow-y-auto p-1"
                        >
                            {hiddenParents.map((node) => (
                                <DropdownMenuItem
                                    key={node.id}
                                    onClick={() => onNavigateFolder(node.id)}
                                    // Same colors as the outer parent crumbs: hint gray at rest, brand on hover.
                                    className="h-8 shrink-0 px-3 py-0 text-caption text-text-3 data-[highlighted]:bg-fill-1 data-[highlighted]:text-blue-600"
                                >
                                    <MenuItemName name={node.name} />
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                    <Separator />
                </span>
            )}
            {tailParents.map((node) => (
                <span key={node.id ?? "space-root"} className="flex shrink-0 items-center gap-0.5">
                    <ParentCrumb node={node} onNavigate={onNavigateFolder} />
                    <Separator />
                </span>
            ))}
            {/* Current page: not clickable, no hover; one shade darker than parents ("you are here"). */}
            <span aria-current="page" className="min-w-0 truncate whitespace-nowrap text-text-1">
                {current.name}
            </span>
        </nav>
    );
}
