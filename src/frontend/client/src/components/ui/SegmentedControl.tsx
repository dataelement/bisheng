import { cn } from "~/utils";

export interface SegmentedControlOption<T extends string> {
    value: T;
    label: string;
}

export interface SegmentedControlProps<T extends string> {
    options: SegmentedControlOption<T>[];
    value: T;
    onChange: (value: T) => void;
    className?: string;
}

/**
 * Grey-track segmented toggle with a sliding white pill (Figma TextButton 12780:52824) —
 * the control behind 频道/广场 on the channel page and 所有/未读 in notifications.
 *
 * Segments share an equal-width grid sized to the widest label, and every label
 * reserves its medium-weight width with an invisible copy, so the active-state
 * font-weight change never resizes the control (visible as jitter in English).
 */
export function SegmentedControl<T extends string>({
    options,
    value,
    onChange,
    className,
}: SegmentedControlProps<T>) {
    const activeIndex = Math.max(0, options.findIndex((option) => option.value === value));

    return (
        <div
            className={cn(
                "relative inline-grid shrink-0 items-center rounded-lg bg-[#EEEEEE] p-[3px]",
                className,
            )}
            style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
        >
            {/* Sliding white indicator — one segment wide, translated to the active segment. */}
            <span
                aria-hidden
                className="pointer-events-none absolute left-[3px] top-[3px] h-[30px] rounded-md bg-white drop-shadow-[0px_4px_2px_rgba(0,0,0,0.05)] transition-transform duration-200 ease-out motion-reduce:transition-none"
                style={{
                    width: `calc((100% - 6px) / ${options.length})`,
                    transform: `translateX(${activeIndex * 100}%)`,
                }}
            />
            {options.map((option) => {
                const isActive = option.value === value;
                return (
                    <button
                        key={option.value}
                        type="button"
                        // Clicking the already-active segment is a no-op.
                        onClick={() => { if (!isActive) onChange(option.value); }}
                        className={cn(
                            "relative z-[1] flex h-[30px] w-full items-center justify-center whitespace-nowrap rounded-md px-3 text-sm leading-[22px] transition-colors",
                            isActive
                                ? "font-medium text-text-1"
                                : "font-normal text-text-3 fine-pointer:hover:text-text-1",
                        )}
                    >
                        <span aria-hidden className="invisible font-medium">{option.label}</span>
                        <span className="absolute inset-0 flex items-center justify-center">{option.label}</span>
                    </button>
                );
            })}
        </div>
    );
}
