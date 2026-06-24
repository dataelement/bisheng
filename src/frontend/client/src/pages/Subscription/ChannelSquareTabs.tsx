import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

type ChannelSquareTab = "channel" | "square";

interface ChannelSquareTabsProps {
    /** Which segment is currently active. */
    active: ChannelSquareTab;
    onChannelClick?: () => void;
    onSquareClick?: () => void;
    className?: string;
}

/** Each segment is a fixed 52px pill; the sliding indicator translates by this much. */
const SEGMENT_WIDTH = 52;

/**
 * Segmented 频道/广场 switcher (Figma TextButton 12780:52824).
 *
 * Rendered once, above both the channel and square views, so switching slides a
 * single white indicator instead of swapping two separately-mounted pills. Grey
 * track with an #ECECEC border; the active label is a white pill with a soft
 * drop shadow that animates between the two positions.
 */
export function ChannelSquareTabs({
    active,
    onChannelClick,
    onSquareClick,
    className,
}: ChannelSquareTabsProps) {
    const localize = useLocalize();

    const segments: { key: ChannelSquareTab; label: string; onClick?: () => void }[] = [
        { key: "channel", label: localize("com_subscription.tab_channel"), onClick: onChannelClick },
        { key: "square", label: localize("com_subscription.tab_square"), onClick: onSquareClick },
    ];

    return (
        <div
            className={cn(
                "relative inline-flex shrink-0 items-center rounded-[8px] bg-[#EEEEEE] p-[3px]",
                className,
            )}
        >
            {/* Sliding white indicator — translates between the two segments. */}
            <span
                aria-hidden
                className="pointer-events-none absolute left-[3px] top-[3px] h-[30px] w-[52px] rounded-[6px] bg-white drop-shadow-[0px_4px_2px_rgba(0,0,0,0.05)] transition-transform duration-200 ease-out motion-reduce:transition-none"
                style={{ transform: `translateX(${active === "square" ? SEGMENT_WIDTH : 0}px)` }}
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
                            "relative z-[1] flex w-[52px] shrink-0 items-center justify-center rounded-[6px] px-3 py-1 text-sm leading-[22px] whitespace-nowrap transition-colors",
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
