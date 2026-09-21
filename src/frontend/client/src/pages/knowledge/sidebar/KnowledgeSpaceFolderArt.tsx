import { useId, type ReactNode } from "react";
import { cn } from "~/utils";

/** Which of the three home sections a tile belongs to — it picks the folder's hue. */
export type KnowledgeSpaceTone = "department" | "created" | "joined";

interface KnowledgeSpaceFolderArtProps {
    /** Section the space belongs to; decides the folder colour. */
    tone: KnowledgeSpaceTone;
    /**
     * How many sheets stand in the folder: 0 → empty, 1, 2, 3+ → full fan. Omit when the
     * caller has no trustworthy whole-space count — the folder then shows the full fan.
     */
    fileCount?: number;
    className?: string;
    /** Rendered on the front cover (name, date, actions). */
    children?: ReactNode;
}

/**
 * Per-section folder tones. Deliberately NOT `--illus-*`: those are one brand-themed ramp,
 * and this grid needs three hues at once to tell 部门 / 我创建的 / 我加入的 apart at a glance —
 * the same reasoning behind the pinned tag colours (--tag-skill etc., 色彩规范 §4). They are
 * fixed across the blue ⇄ green themes for that reason, and kept low-saturation (S ≈ 45–55%,
 * L ≈ 88–93%) so a wall of folders stays calm and the name on the cover stays readable.
 */
const TONES: Record<KnowledgeSpaceTone, { tint: string; mid: string; deep: string }> = {
    department: { tint: "#E9F1FB", mid: "#CEDFF3", deep: "#B2C9E5" },
    created: { tint: "#E9F3EC", mid: "#CBE3D4", deep: "#ACCFBA" },
    joined: { tint: "#F1ECFA", mid: "#DCD3F1", deep: "#C4B7E4" },
};

/**
 * Folder outline, drawn in a 120×90 box (the tile's 4:3). ONE standard silhouette for every
 * tile: a body with a single tab on the top-left, and a front cover that is exactly as wide
 * as the back. The covers sharing an outline is what makes BACK_PATH the folder's whole
 * silhouette — the ghost tile (KnowledgeSpaceGhostTile) draws just that one path dashed.
 */
export const FOLDER_BACK_PATH =
    "M2 15Q2 9 8 9L44 9Q49 9 51.5 13L54.5 18Q57 22 62 22L112 22Q118 22 118 28L118 82Q118 88 112 88L8 88Q2 88 2 82Z";
const FOLDER_FRONT_PATH =
    "M2 46Q2 40 8 40L112 40Q118 40 118 46L118 82Q118 88 112 88L8 88Q2 88 2 82Z";

type Sheet = {
    /** Top-left corner inside the fan; every sheet is the same size. */
    x: number;
    y: number;
    /**
     * Resting tilt and the hover fan, both as CSS transforms rather than the SVG `transform`
     * attribute — a class can carry the `group-hover:` state, and both copies of the sheet
     * (sharp above the cover, blurred behind it) pick up exactly the same motion, so they
     * never drift apart at the cover's edge.
     */
    rest: string;
    hover: string;
    /** White surface unless tinted, in which case it takes the tone's lightest step. */
    tinted: boolean;
};

// Back-to-front: the last sheet sits on top, upright, flanked by two tilted ones that start 7
// units LOWER, so the three tops stagger instead of ruling one straight line across the tile.
// Full-height sheets that stand well PROUD of the back cover — they are the subject of the
// drawing, the folder only holds them. (Tucking them inside the silhouette was tried and read
// as a smear of tiny white bars at tile size.) Geometry is the pre-SVG DOM layout converted
// into user units: 44% × 78% of the tile, flanks inset 12%.
const SHEET_W = 53;
const SHEET_H = 70;
const SHEETS: Sheet[] = [
    {
        x: 14,
        y: 8,
        tinted: true,
        rest: "[transform:rotate(-9deg)]",
        hover: "group-hover:[transform:translateY(-3px)_rotate(-12deg)]",
    },
    {
        x: 53,
        y: 8,
        tinted: false,
        rest: "[transform:rotate(9deg)]",
        hover: "group-hover:[transform:translateY(-3px)_rotate(12deg)]",
    },
    {
        x: 33.5,
        y: 1,
        tinted: false,
        rest: "[transform:rotate(0deg)]",
        hover: "group-hover:[transform:translateY(-6px)]",
    },
];

// Which sheets show for 1 / 2 / 3+ files (indexes into SHEETS, kept in paint order).
const VISIBLE_SHEETS: number[][] = [[], [2], [0, 2], [0, 1, 2]];

/**
 * Folder tile art for the knowledge-space home grid: a fan of document sheets standing
 * between a folder's back cover and its translucent front cover.
 *
 * The frosted front is a REAL blur: the sheets are painted twice — sharp above the cover's
 * top edge, and blurred (feGaussianBlur) where the cover overlaps them — then a translucent
 * tinted fill goes on top. This is NOT `backdrop-filter` (banned on anything that scales with
 * content — root AGENTS.md §4): there is no backdrop, so at rest every tile holds a cached
 * raster and costs nothing. The hover fan does re-run the filter, but only for the ONE tile
 * under the cursor and only over its own ~150×110px box, which is the difference that made
 * backdrop-filter untenable: that one re-snapshotted the whole page behind every element,
 * every frame, on every tile at once.
 */
export function KnowledgeSpaceFolderArt({
    tone,
    fileCount,
    className,
    children,
}: KnowledgeSpaceFolderArtProps) {
    const colors = TONES[tone];
    const visible = VISIBLE_SHEETS[Math.min(Math.max(fileCount ?? 3, 0), 3)];
    // SVG ids are document-global; one set per tile.
    // useId() emits ":r0:" tokens — strip the colons so they are valid in url() refs.
    const uid = useId().replace(/:/g, "");
    const aboveCoverId = `${uid}-above`;
    const coverClipId = `${uid}-cover`;
    const blurId = `${uid}-blur`;
    const coverFillId = `${uid}-fill`;
    const backFillId = `${uid}-back`;

    const sheets = (
        <g>
            {visible.map((index) => {
                const sheet = SHEETS[index];
                const surface = sheet.tinted ? colors.tint : "#fff";
                const line = sheet.tinted ? colors.mid : colors.tint;
                return (
                    <g
                        key={index}
                        // fill-box makes `transform-origin: center` mean the sheet's own centre,
                        // which is what the resting rotation turns about.
                        className={cn(
                            "[transform-box:fill-box] [transform-origin:center]",
                            "transition-transform duration-200 ease-out motion-reduce:transition-none",
                            sheet.rest,
                            sheet.hover,
                        )}
                    >
                        <rect
                            x={sheet.x}
                            y={sheet.y}
                            width={SHEET_W}
                            height={SHEET_H}
                            rx={4}
                            fill={surface}
                            stroke={colors.mid}
                            strokeWidth={0.5}
                        />
                        <rect x={sheet.x + 3.5} y={sheet.y + 4} width={29} height={4.2} rx={2.1} fill={colors.deep} />
                        <rect x={sheet.x + 3.5} y={sheet.y + 16} width={46} height={2.8} rx={1.4} fill={line} />
                        <rect x={sheet.x + 3.5} y={sheet.y + 24} width={37} height={2.8} rx={1.4} fill={line} />
                    </g>
                );
            })}
        </g>
    );

    return (
        <div
            className={cn("relative aspect-[4/3] w-full", className)}
        >
            {/* overflow-visible: tilting a full-height sheet lifts its corner above the viewBox —
                2.7 user units at rest, 6.7 at the top of the hover fan — and an SVG viewport
                clips that to a flat cut across the paper. The sheets stood proud of their box in
                the DOM version too; the grid's own py-3 leaves more room than the overhang needs,
                and nothing pokes out sideways (the widest sheet reaches x=112.7 of 120). */}
            <svg viewBox="0 0 120 90" className="absolute inset-0 size-full overflow-visible" aria-hidden>
                <defs>
                    {/* Everything the front cover overlaps is masked out of the sharp copy and
                        drawn by the blurred one instead — a proper frosted-glass composite. */}
                    <mask id={aboveCoverId}>
                        <rect x="-10" y="-10" width="140" height="110" fill="#fff" />
                        <path d={FOLDER_FRONT_PATH} fill="#000" />
                    </mask>
                    <clipPath id={coverClipId}>
                        <path d={FOLDER_FRONT_PATH} />
                    </clipPath>
                    <filter id={blurId} x="-20%" y="-20%" width="140%" height="140%">
                        <feGaussianBlur stdDeviation="1.8" />
                    </filter>
                    <linearGradient id={backFillId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0" stopColor={colors.mid} />
                        <stop offset="1" stopColor={colors.deep} />
                    </linearGradient>
                    <linearGradient id={coverFillId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0" stopColor={colors.tint} stopOpacity="0.46" />
                        <stop offset="1" stopColor={colors.tint} stopOpacity="0.8" />
                    </linearGradient>
                </defs>

                {/* Back cover + the sheets standing in it. */}
                <path d={FOLDER_BACK_PATH} fill={`url(#${backFillId})`} />
                <g mask={`url(#${aboveCoverId})`}>{sheets}</g>

                {/* Front cover: the sheets behind it, blurred and clipped to the cover, then a
                    translucent tint and a hairline rim to hold the pale shape on a white page. */}
                <g clipPath={`url(#${coverClipId})`}>
                    <g filter={`url(#${blurId})`} opacity="0.9">
                        {sheets}
                    </g>
                    <path d={FOLDER_FRONT_PATH} fill="#fff" fillOpacity="0.3" />
                    <path d={FOLDER_FRONT_PATH} fill={`url(#${coverFillId})`} />
                </g>
                <path
                    d={FOLDER_FRONT_PATH}
                    fill="none"
                    strokeWidth={0.6}
                    stroke={colors.deep}
                    strokeOpacity={0.5}
                />
                {/* Top-edge highlight — the lip of the cover catching light. */}
                <path
                    d="M8 40.6L112 40.6"
                    fill="none"
                    strokeWidth={0.8}
                    stroke="#fff"
                    strokeOpacity={0.7}
                    strokeLinecap="round"
                />
            </svg>

            {/* Label area = the front cover below its top edge (FRONT_PATH y 40 → 88). */}
            {children ? (
                <div className="absolute inset-x-0 bottom-0 flex h-[53%] flex-col justify-end px-3 pb-2.5">
                    {children}
                </div>
            ) : null}
        </div>
    );
}

/** Ghost variants reuse the filled tones, so the two tiles read as the same family. */
export function knowledgeSpaceToneColors(tone: KnowledgeSpaceTone) {
    return TONES[tone];
}
