import { cn } from "~/utils";

interface RoundCheckboxProps {
    checked: boolean;
    onCheckedChange: (checked: boolean) => void;
    className?: string;
}

/**
 * Circular checkbox (~20px) used in the H5 mobile file row.
 * - Unchecked: transparent fill with a 1.5px #D9D9D9 ring.
 * - Checked: a #165DFF ring with a solid blue filled center dot (radio-like).
 * Click propagation is stopped so toggling selection never triggers the row's onClick.
 */
export function RoundCheckbox({ checked, onCheckedChange, className }: RoundCheckboxProps) {
    return (
        <button
            type="button"
            role="checkbox"
            aria-checked={checked}
            className={cn(
                "flex size-5 shrink-0 items-center justify-center rounded-full outline-none",
                className,
            )}
            onPointerDown={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => {
                e.stopPropagation();
                onCheckedChange(!checked);
            }}
        >
            {/* 20x20 hit area, 12x12 visible circle. */}
            {checked ? (
                // Blue ring + solid blue center dot (radio-like).
                <span className="flex size-3 items-center justify-center rounded-full border-[1.5px] border-[#165DFF] bg-white">
                    <span className="size-1.5 rounded-full bg-[#165DFF]" />
                </span>
            ) : (
                <span className="size-3 rounded-full border-[1.5px] border-[#D9D9D9] bg-transparent" />
            )}
        </button>
    );
}
