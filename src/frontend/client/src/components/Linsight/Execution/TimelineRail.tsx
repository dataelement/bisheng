/**
 * TimelineRail — shared left-rail primitive for task-mode timeline items.
 *
 * Mirrors the left rail of the daily /c ThinkingContent (16px icon slot + 1px
 * vertical connector) token-for-token, so task-mode groups/rows line up exactly
 * with the daily "深度思考" timeline. This is a task-mode-local copy of the North
 * Star tokens — it does NOT import or modify any Chat/Messages component.
 *
 * Rail anatomy (from ThinkingContent):
 *   flex shrink-0 flex-col items-center gap-0.5 self-stretch pt-[3px]
 *     ├─ size-4 icon slot (centered)
 *     └─ w-px flex-1 connector in HAIRLINE (rendered when showConnector)
 */
import { type CSSProperties, type FC, type ReactNode } from 'react';
import { HAIRLINE } from './execTokens';

export interface TimelineRailProps {
    /** Leading glyph (status icon / tool icon), sized 16px by the caller. */
    icon: ReactNode;
    /**
     * Render the vertical connector below the icon. Set true when this item is
     * expanded (the rail must flank its open body) or when something follows in
     * the timeline, keeping the spine continuous.
     */
    showConnector?: boolean;
}

/** Connector color is the shared Hairline token (replaces legacy #E0E0E0). */
const connectorStyle: CSSProperties = { backgroundColor: HAIRLINE };

const TimelineRail: FC<TimelineRailProps> = ({ icon, showConnector = false }) => (
    <div className="flex shrink-0 flex-col items-center gap-0.5 self-stretch pt-[3px]">
        <span className="flex size-4 shrink-0 items-center justify-center">{icon}</span>
        {showConnector && <div className="w-px flex-1" style={connectorStyle} aria-hidden="true" />}
    </div>
);

TimelineRail.displayName = 'TimelineRail';

export default TimelineRail;
