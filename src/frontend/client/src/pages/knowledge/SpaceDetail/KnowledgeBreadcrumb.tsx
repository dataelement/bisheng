import { useState } from "react";
import { Outlined } from "bisheng-icons";
import { cn } from "~/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "~/components/ui/HoverCard";

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
/** When the chain exceeds 5 levels, collapse the middle into an ellipsis (design 2075:8134). */
const COLLAPSE_THRESHOLD = 5;

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
                <TooltipContent noArrow side="bottom" className="z-[999] bg-white px-3 py-2 text-sm text-[#4e5969] shadow-md">
                    {node.name}
                </TooltipContent>
            )}
        </Tooltip>
    );
}

/**
 * Folder path breadcrumb above the knowledge-space header title (desktop only; design 2075:8134).
 * Hidden at the space root ("single level" case) — the caller only renders it inside a folder.
 */
export function KnowledgeBreadcrumb({ spaceName, currentPath, onNavigateFolder, className }: KnowledgeBreadcrumbProps) {
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
                    <HoverCard openDelay={100} closeDelay={150}>
                        <HoverCardTrigger asChild>
                            <span className="cursor-pointer px-0.5 text-text-3 transition-colors hover:text-blue-600">
                                ...
                            </span>
                        </HoverCardTrigger>
                        <HoverCardContent
                            align="start"
                            className="flex w-auto max-w-[420px] flex-wrap items-center gap-x-0.5 gap-y-1 rounded-lg border border-border-base bg-white px-4 py-2 text-caption leading-6 text-text-3 shadow-md"
                        >
                            {hiddenParents.map((node, idx) => (
                                <span key={node.id} className="flex shrink-0 items-center gap-0.5">
                                    {idx > 0 && <Separator />}
                                    <ParentCrumb node={node} onNavigate={onNavigateFolder} />
                                </span>
                            ))}
                        </HoverCardContent>
                    </HoverCard>
                    <Separator />
                </span>
            )}
            {tailParents.map((node) => (
                <span key={node.id ?? "space-root"} className="flex shrink-0 items-center gap-0.5">
                    <ParentCrumb node={node} onNavigate={onNavigateFolder} />
                    <Separator />
                </span>
            ))}
            {/* Current page: not clickable, no hover effect, only limited by the row width. */}
            <span aria-current="page" className="min-w-0 truncate whitespace-nowrap">
                {current.name}
            </span>
        </nav>
    );
}
