import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

type ChannelSquareTab = "channel" | "square";

interface ChannelSquareTabsProps {
    /** Which segment is currently active. */
    active: ChannelSquareTab;
    onChannelClick?: () => void;
    onSquareClick?: () => void;
    className?: string;
    /** "segmented" = PC grey pill toggle. "underline" = H5 text tabs with a blue underline bar. */
    variant?: "segmented" | "underline";
    /** Grey out + block interaction (H5: while the channel-switcher dropdown is open). */
    disabled?: boolean;
}

/**
 * Segmented 频道/广场 switcher (Figma TextButton 12780:52824).
 *
 * Rendered once, above both the channel and square views, so switching slides a
 * single white indicator instead of swapping two separately-mounted pills. Grey
 * track; the active label is a white pill with a soft drop shadow that animates
 * between the two positions.
 *
 * Width is content-driven (not fixed px) so longer labels in other locales —
 * e.g. "Channels" / "Square" — never clip: the two segments share an equal-width
 * grid sized to the widest label, and the indicator uses a percentage width so
 * it always matches a segment.
 */
export function ChannelSquareTabs({
    active,
    onChannelClick,
    onSquareClick,
    className,
    variant = "segmented",
    disabled = false,
}: ChannelSquareTabsProps) {
    const localize = useLocalize();

    const segments: { key: ChannelSquareTab; label: string; onClick?: () => void }[] = [
        { key: "channel", label: localize("com_subscription.tab_channel"), onClick: onChannelClick },
        { key: "square", label: localize("com_subscription.tab_square"), onClick: onSquareClick },
    ];

    // --- Underline-variant sliding indicator (H5) ---
    // A single blue bar slides between the two tabs. We measure the active tab's
    // offset/width relative to the row so the bar tracks each label's real width
    // (robust to longer non-CJK labels). transform+width are animated; the mount
    // frame is non-animated so the bar appears in place without an entrance slide.
    const rowRef = useRef<HTMLDivElement>(null);
    const tabRefs = useRef<Partial<Record<ChannelSquareTab, HTMLButtonElement | null>>>({});
    const [indicator, setIndicator] = useState<{ left: number; width: number }>({ left: 0, width: 0 });
    const [animate, setAnimate] = useState(false);

    useLayoutEffect(() => {
        if (variant !== "underline") return;
        const row = rowRef.current;
        const tab = tabRefs.current[active];
        if (!row || !tab) return;
        const measure = () => {
            const r = row.getBoundingClientRect();
            const t = tab.getBoundingClientRect();
            setIndicator({ left: t.left - r.left, width: t.width });
        };
        measure();
        // Label width can change with viewport/locale/font load — re-measure on resize.
        const ro = new ResizeObserver(measure);
        ro.observe(row);
        ro.observe(tab);
        return () => ro.disconnect();
    }, [variant, active, segments[0].label, segments[1].label]);

    // Enable the slide transition only after the first measured frame has painted.
    useEffect(() => {
        if (variant !== "underline") return;
        const id = requestAnimationFrame(() => setAnimate(true));
        return () => cancelAnimationFrame(id);
    }, [variant]);

    // H5 underline tabs — plain text on white, the active label medium-weight #212121,
    // the inactive label grey/regular. The bar is absolutely positioned below the text
    // so only the TEXT is vertically centered with the neighbouring header buttons.
    if (variant === "underline") {
        return (
            <div
                ref={rowRef}
                className={cn(
                    "relative flex items-center gap-4 transition-opacity",
                    disabled && "pointer-events-none opacity-20",
                    className,
                )}
            >
                {segments.map((seg) => {
                    const isActive = active === seg.key;
                    return (
                        <button
                            key={seg.key}
                            ref={(el) => { tabRefs.current[seg.key] = el; }}
                            type="button"
                            disabled={disabled}
                            // Clicking the already-active segment is a no-op.
                            onClick={() => { if (!isActive) seg.onClick?.(); }}
                            className="relative flex items-center outline-none"
                        >
                            <span
                                className={cn(
                                    "text-base leading-6 whitespace-nowrap transition-colors duration-200",
                                    isActive ? "font-medium text-[#212121]" : "font-normal text-[#C9CDD4]",
                                )}
                            >
                                {seg.label}
                            </span>
                        </button>
                    );
                })}
                {/* Single blue bar that slides between the two tabs. */}
                <span
                    aria-hidden
                    className="pointer-events-none absolute -bottom-1.5 left-0 h-0.5 rounded-full bg-blue-500 motion-reduce:transition-none"
                    style={{
                        width: indicator.width,
                        transform: `translateX(${indicator.left}px)`,
                        opacity: indicator.width ? 1 : 0,
                        transition: animate
                            ? "transform 250ms ease-out, width 250ms ease-out"
                            : "none",
                    }}
                />
            </div>
        );
    }

    return (
        <div
            className={cn(
                "relative inline-grid grid-cols-2 shrink-0 items-center rounded-[8px] bg-[#EEEEEE] p-[3px]",
                className,
            )}
        >
            {/* Sliding white indicator — half the inner width, translated between the two segments. */}
            <span
                aria-hidden
                className="pointer-events-none absolute left-[3px] top-[3px] h-[30px] w-[calc((100%-6px)/2)] rounded-[6px] bg-white drop-shadow-[0px_4px_2px_rgba(0,0,0,0.05)] transition-transform duration-200 ease-out motion-reduce:transition-none"
                style={{ transform: `translateX(${active === "square" ? "100%" : "0%"})` }}
            />
            {segments.map((seg) => {
                const isActive = active === seg.key;
                return (
                    <button
                        key={seg.key}
                        type="button"
                        // Clicking the already-active segment is a no-op.
                        onClick={() => { if (!isActive) seg.onClick?.(); }}
                        className={cn(
                            "relative z-[1] flex h-[30px] w-full items-center justify-center rounded-[6px] px-3 text-sm leading-[22px] whitespace-nowrap transition-colors",
                            isActive
                                ? "font-medium text-[#212121]"
                                : "font-normal text-[#999999] fine-pointer:hover:text-[#212121]",
                        )}
                    >
                        {seg.label}
                    </button>
                );
            })}
        </div>
    );
}
