/**
 * CollapsibleTimelineItem — shared collapsible timeline item for task mode.
 *
 * One node = TimelineRail (left) + a controlled trigger button + a grid
 * 0fr→1fr expand animation around `children`. Token-for-token copy of the daily
 * /c ThinkingContent trigger/animation (it does NOT import or touch any
 * Chat/Messages component): trigger title `#999999` hover→`#212121`, optional
 * trailing `summary` slot in `text-gray-400`, a single chevron that rotates
 * 180° when open, and a `grid transition-all duration-300 ease-out` body.
 *
 * `open` is fully controlled by the parent (groups own their expand state so a
 * single source of truth survives session persistence / live append). The
 * connector under the rail is drawn while `open` so the spine flanks the body.
 */
import { Outlined } from 'bisheng-icons';
import { useCallback, type FC, type MouseEvent, type ReactNode } from 'react';
import { cn } from '~/utils';
import { INK, MUTED } from './execTokens';
import TimelineRail from './TimelineRail';

export interface CollapsibleTimelineItemProps {
    /** Leading glyph for the rail (16px), e.g. an Outlined status icon. */
    icon: ReactNode;
    /** Trigger title. Muted (#8A8A8A) by default, hover→Ink (#1D2129). */
    label: ReactNode;
    /** Optional trailing summary (e.g. the readable "联网搜索 3 次 · 用时 12 秒"
     *  activity meta from summarizeActivity), muted gray. */
    summary?: ReactNode;
    /** Pulse the trigger title while the node is active/streaming. */
    streaming?: boolean;
    /** Controlled open state — owned by the parent. */
    open: boolean;
    /** Toggle handler; receives the next open state. */
    onToggle: (next: boolean) => void;
    /**
     * Optional stable id of the group this item represents (F7). Persistence
     * lives in the PARENT (via `useCollapseState`), keeping this component
     * purely controlled; `persistKey` is an auxiliary marker only — it is
     * surfaced as a `data-persist-key` attribute for debugging/testing and does
     * NOT alter the controlled `open`/`onToggle` contract.
     */
    persistKey?: string;
    /** Body revealed when open; the grid animates its height. */
    children: ReactNode;
    className?: string;
}

const CollapsibleTimelineItem: FC<CollapsibleTimelineItemProps> = ({
    icon,
    label,
    summary,
    streaming = false,
    open,
    onToggle,
    children,
    className,
    persistKey,
}) => {
    const handleClick = useCallback(
        (e: MouseEvent<HTMLButtonElement>) => {
            e.preventDefault();
            onToggle(!open);
        },
        [open, onToggle],
    );

    return (
        <div
            className={cn('flex w-full min-w-0 gap-1.5 animate-thinking-appear', className)}
            data-persist-key={persistKey}
        >
            {/* Rail connector flanks the body only while open (per-node spine,
                mirroring the daily "思考内容" rail). */}
            <TimelineRail icon={icon} showConnector={open} />
            <div className="flex min-w-0 flex-1 flex-col pb-3">
                <button
                    type="button"
                    onClick={handleClick}
                    style={{ color: MUTED }}
                    className={cn(
                        // Muted base, Ink on hover (token-ized; was #999999/#212121).
                        'group flex w-fit max-w-full items-center gap-1 text-sm leading-[22px] transition-colors',
                        streaming && 'animate-pulse',
                    )}
                    onMouseEnter={(e) => { e.currentTarget.style.color = INK; }}
                    onMouseLeave={(e) => { e.currentTarget.style.color = MUTED; }}
                >
                    <span className="min-w-0 truncate">{label}</span>
                    <Outlined.Down
                        size={16}
                        className={cn(
                            'shrink-0 transform-gpu transition-transform duration-200',
                            open && 'rotate-180',
                        )}
                    />
                    {summary != null && (
                        <span className="shrink-0" style={{ color: MUTED }}>{summary}</span>
                    )}
                </button>
                <div
                    className={cn('grid transition-all duration-300 ease-out', open && 'mt-2')}
                    style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
                >
                    <div className="min-h-0 overflow-hidden">{children}</div>
                </div>
            </div>
        </div>
    );
};

CollapsibleTimelineItem.displayName = 'CollapsibleTimelineItem';

export default CollapsibleTimelineItem;
