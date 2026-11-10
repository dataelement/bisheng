import { Outlined } from "bisheng-icons";
import { cn } from "~/utils";
import {
    FOLDER_BACK_PATH,
    knowledgeSpaceToneColors,
    type KnowledgeSpaceTone,
} from "./KnowledgeSpaceFolderArt";

interface KnowledgeSpaceGhostTileProps {
    /** Section this tile leads the grid of — it borrows that section's folder colour. */
    tone: KnowledgeSpaceTone;
    label: string;
    onClick: () => void;
    className?: string;
}

/**
 * The dashed folder that opens each actionable section of the home grid: 我创建的 starts with
 * "create a space", 我加入的 with "go find one in the square". Same silhouette as a real tile
 * (FOLDER_BACK_PATH is the whole outline — the two covers are the same width), drawn as an
 * empty dashed outline so it reads as a slot waiting to be filled rather than a space.
 */
export function KnowledgeSpaceGhostTile({ tone, label, onClick, className }: KnowledgeSpaceGhostTileProps) {
    const colors = knowledgeSpaceToneColors(tone);

    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={label}
            className={cn("group block w-full text-left outline-none", className)}
        >
            <div className="relative aspect-[4/3] w-full transition-transform duration-200 ease-out group-hover:-translate-y-1 motion-reduce:transition-none">
                <svg viewBox="0 0 120 90" className="absolute inset-0 size-full" aria-hidden>
                    <path
                        d={FOLDER_BACK_PATH}
                        fill={colors.tint}
                        fillOpacity={0.45}
                        stroke={colors.deep}
                        strokeWidth={1}
                        strokeDasharray="4 3"
                        strokeLinejoin="round"
                        className="transition-[fill-opacity] duration-200 group-hover:[fill-opacity:0.8] motion-reduce:transition-none"
                    />
                </svg>
                {/* Sits low on the folder's front cover — the plus straddles the cover's top edge
                    and the label rides between the neighbouring tiles' name and date rows (label
                    bottom at 85% of the tile's height). Centred in the whole dashed box floated too
                    high at 72%; flush with the real tiles' date row sank too low at 91%. */}
                <div className="absolute inset-x-0 bottom-[15%] flex flex-col items-center gap-1 px-3">
                    <span
                        className="flex size-7 items-center justify-center rounded-full"
                        style={{ background: colors.deep }}
                    >
                        <Outlined.Plus className="size-4 text-white" aria-hidden />
                    </span>
                    <span className="line-clamp-2 text-center text-caption text-text-2">{label}</span>
                </div>
            </div>
        </button>
    );
}
