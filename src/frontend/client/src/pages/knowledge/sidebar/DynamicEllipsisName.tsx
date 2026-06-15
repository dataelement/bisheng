import type { ReactNode } from "react";
import { cn } from "~/utils";

interface DynamicEllipsisNameProps {
    name: string;
    /** Classes applied to the text itself (font size / colour / weight). */
    textClassName?: string;
    /** Inline content rendered after the name (e.g. a pin icon). Should be shrink-0. */
    trailing?: ReactNode;
    /** Extra classes for the outer positioning cell. */
    className?: string;
    onDoubleClick?: () => void;
}

/**
 * A name label whose truncation point follows horizontal scroll (see
 * useDynamicEllipsis). It renders two copies:
 *  • an invisible, natural-width spacer that keeps the row as wide as the full
 *    name so the container can scroll to reveal more of it;
 *  • an absolutely-positioned visible overlay (tagged `[data-ellipsis-text]`)
 *    whose max-width the hook sets each frame so the ellipsis sits at the
 *    viewport's right edge.
 */
export function DynamicEllipsisName({
    name,
    textClassName,
    trailing,
    className,
    onDoubleClick,
}: DynamicEllipsisNameProps) {
    return (
        <div className={cn("relative self-stretch", className)}>
            {/* Spacer: drives the row's natural (scrollable) width. */}
            <span
                aria-hidden
                className="invisible flex h-full items-center gap-1 whitespace-nowrap pl-1"
            >
                <span className={textClassName}>{name}</span>
                {trailing}
            </span>

            {/* Visible overlay: out of flow, clipped to a hook-controlled max-width. */}
            <span
                data-ellipsis-text
                onDoubleClick={onDoubleClick}
                className="absolute inset-y-0 left-0 flex items-center gap-1 overflow-hidden whitespace-nowrap pl-1"
            >
                <span className={cn("min-w-0 overflow-hidden text-ellipsis", textClassName)}>
                    {name}
                </span>
                {trailing}
            </span>
        </div>
    );
}
