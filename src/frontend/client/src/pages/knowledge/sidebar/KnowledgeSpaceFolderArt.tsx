import { useId, type ReactNode } from "react";
import { cn } from "~/utils";

interface KnowledgeSpaceFolderArtProps {
    /**
     * How many sheets stand in the folder: 0 → empty, 1, 2, 3+ → full fan. Omit when the
     * caller has no trustworthy whole-space count — the folder then shows the full fan.
     */
    fileCount?: number;
    className?: string;
    /** Rendered on the front cover (name, date, actions). */
    children?: ReactNode;
}

type Sheet = {
    /** Position / tilt of the sheet inside the fan. */
    className: string;
    /** Sheet surface; brand tones come from the --illus-* palette so they follow the theme. */
    background: string;
    lines: string;
};

// Back-to-front: the last sheet sits on top, upright, flanked by two tilted ones.
const SHEETS: Sheet[] = [
    {
        className: "left-[12%] -rotate-[9deg] group-hover:-translate-y-1 group-hover:-rotate-[12deg]",
        background: "rgb(var(--illus-100))",
        lines: "rgb(var(--illus-300))",
    },
    {
        className: "right-[12%] rotate-[9deg] group-hover:-translate-y-1 group-hover:rotate-[12deg]",
        // Kept pale: a mid-tone sheet would melt into the deep back cover behind it.
        background: "#fff",
        lines: "rgb(var(--illus-300))",
    },
    {
        className: "left-1/2 -translate-x-1/2 group-hover:-translate-y-2",
        background: "#fff",
        lines: "rgb(var(--illus-100))",
    },
];

// Which sheets show for 1 / 2 / 3+ files (indexes into SHEETS, kept in paint order).
const VISIBLE_SHEETS: number[][] = [[], [2], [0, 2], [0, 1, 2]];

// Folder outlines, drawn in a 120×90 box (the tile's 4:3). Back cover: body plus a tab on
// the top-right. Front cover: slightly wider than the back, with the classic raised step
// on the top-left sloping down to the lower right-hand edge.
const BACK_PATH =
    "M4 22Q4 14 12 14L66 14C73 14 75 6 82 6L108 6Q116 6 116 14L116 82Q116 90 108 90L12 90Q4 90 4 82Z";
const FRONT_PATH =
    "M0 43Q0 35 8 35L40 35C47 35 49 44 56 44L112 44Q120 44 120 52L120 82Q120 90 112 90L8 90Q0 90 0 82Z";

/**
 * Folder tile art for the knowledge-space home grid: a fan of document sheets standing
 * between a folder's back cover and its translucent front cover. The front imitates
 * frosted glass WITHOUT `backdrop-filter` (banned on anything that scales with content —
 * root AGENTS.md §4): a mostly-opaque fill just lets the sheets ghost through. Hover motion
 * is transform-only; the parent must carry `group`.
 */
export function KnowledgeSpaceFolderArt({ fileCount, className, children }: KnowledgeSpaceFolderArtProps) {
    const visible = VISIBLE_SHEETS[Math.min(Math.max(fileCount ?? 3, 0), 3)];
    // SVG ids are document-global; one pair per tile.
    // useId() emits ":r0:" tokens — strip the colons so they are valid in url() refs.
    const uid = useId().replace(/:/g, "");
    const frontFillId = `${uid}-front`;
    const edgeId = `${uid}-edge`;

    return (
        <div className={cn("relative aspect-[4/3] w-full", className)}>
            {/* Back cover — clearly deeper than the front so the two read apart even when empty.
                SVG presentation attributes ignore var(), hence inline `style` for every colour. */}
            <svg viewBox="0 0 120 90" className="absolute inset-0 size-full" aria-hidden>
                <path d={BACK_PATH} style={{ fill: "rgb(var(--illus-300))" }} />
                <path d={BACK_PATH} style={{ fill: "rgb(var(--illus-500))", fillOpacity: 0.18 }} />
            </svg>

            {visible.map((index) => {
                const sheet = SHEETS[index];
                return (
                    <div
                        key={index}
                        aria-hidden
                        className={cn(
                            "absolute top-[1%] h-[78%] w-[44%] rounded-md p-[6%] shadow-[0_1px_5px_rgb(0_0_0/0.12),0_0_0_0.5px_rgb(0_0_0/0.06)]",
                            "transition-transform duration-200 ease-out motion-reduce:transition-none",
                            sheet.className,
                        )}
                        style={{ background: sheet.background }}
                    >
                        <div className="h-[6%] w-[55%] rounded-full" style={{ background: "rgb(var(--illus-500))" }} />
                        <div className="mt-[12%] h-[4%] w-full rounded-full" style={{ background: sheet.lines }} />
                        <div className="mt-[8%] h-[4%] w-[80%] rounded-full" style={{ background: sheet.lines }} />
                    </div>
                );
            })}

            {/* Front cover. Deliberately quiet: a hairline rim to hold the pale shape on a white
                page, plus a top-edge highlight that fades out before the sides — no drop shadow,
                no glow. */}
            <svg viewBox="0 0 120 90" className="absolute inset-0 size-full" aria-hidden>
                <defs>
                    <linearGradient id={frontFillId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0" style={{ stopColor: "rgb(var(--illus-100))", stopOpacity: 0.86 }} />
                        <stop offset="1" style={{ stopColor: "rgb(var(--illus-100))", stopOpacity: 0.97 }} />
                    </linearGradient>
                    <linearGradient id={edgeId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0" style={{ stopColor: "#fff", stopOpacity: 0.6 }} />
                        <stop offset="0.3" style={{ stopColor: "#fff", stopOpacity: 0 }} />
                    </linearGradient>
                </defs>
                <path d={FRONT_PATH} style={{ fill: "#fff", fillOpacity: 0.35 }} />
                <path d={FRONT_PATH} fill={`url(#${frontFillId})`} />
                <path
                    d={FRONT_PATH}
                    fill="none"
                    strokeWidth={0.5}
                    style={{ stroke: "rgb(var(--illus-300))", strokeOpacity: 0.55 }}
                />
                <path
                    d={FRONT_PATH}
                    fill="none"
                    strokeWidth={0.75}
                    transform="translate(0 0.6)"
                    stroke={`url(#${edgeId})`}
                />
            </svg>

            {/* Label area = the front cover below its step (FRONT_PATH y 44 → 90). */}
            {children ? (
                <div className="absolute inset-x-0 bottom-0 flex h-[51%] flex-col justify-end px-3 pb-2.5">
                    {children}
                </div>
            ) : null}
        </div>
    );
}
