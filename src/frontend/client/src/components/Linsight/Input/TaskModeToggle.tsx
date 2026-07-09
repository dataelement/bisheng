/**
 * F035 Track H: task-mode toggle button shown in the input toolbar (right of
 * tools when in task mode). Default icon matches the "+" menu task-mode entry
 * (Outlined.Binoculars); on hover it swaps to an "x" (exit affordance). No
 * default background; hover uses a light primary tint, rounded like the other
 * toolbar buttons.
 */
import { X } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { useLocalize, useMediaQuery } from '~/hooks';
import { cn } from '~/utils';

interface TaskModeToggleProps {
    active: boolean;
    disabled?: boolean;
    onClick: () => void;
    /**
     * Toolbar ran out of room (measured by the parent, see useContainerCompact):
     * collapse to icon-only with a persistent exit "x". When compact, the hover
     * icon-swap is disabled — otherwise it renders a SECOND x next to the
     * persistent one. Roomy toolbars keep the hover binoculars→x affordance.
     */
    compact?: boolean;
}

export function TaskModeToggle({ active, disabled = false, onClick, compact = false }: TaskModeToggleProps) {
    const localize = useLocalize();
    const [hovered, setHovered] = useState(false);
    // Touch devices (iPad, foldables) can't hover, so the binoculars→x swap
    // never fires there — fall back to a persistent exit "x" even when the label
    // is shown. The swap stays only on hover-capable, roomy layouts.
    const noHover = useMediaQuery('(hover: none)');
    const showExit = active && hovered && !compact && !noHover;
    // Standing exit "x": when there's no hover-swap to reveal it (compact layout
    // or a non-hover device).
    const showPersistentExit = active && (compact || noHover);

    return (
        <button
            type="button"
            disabled={disabled}
            onClick={onClick}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            aria-label={showExit ? localize('com_linsight_exit_task_mode') : localize('com_linsight_task_mode')}
            className={cn(
                // primary-100 is not a theme token; use a light primary tint to match.
                'flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-[13px] font-normal transition-colors outline-none hover:bg-blue-100',
                active ? 'text-blue-600' : 'text-[#4E5969]',
                disabled && 'cursor-not-allowed opacity-50',
            )}
        >
            {showExit ? (
                <X size={16} className="text-blue-600" />
            ) : (
                <Outlined.Binoculars size={16} className={active ? 'text-blue-600' : 'text-[#4E5969]'} />
            )}
            {/* Compact: collapse to icon only to save horizontal space in the
                input toolbar, matching the knowledge/tools selectors. */}
            {!compact && <span>{localize('com_linsight_task_mode')}</span>}
            {/* Persistent exit "x" standing in for the other selectors' chevron
                — same size/color/gap as their down icon (size 16, #999). Shown
                when no hover-swap will reveal one: compact layout, or a device
                that can't hover. Hover-capable roomy layouts use the swap above. */}
            {showPersistentExit && (
                <X size={16} className="shrink-0 text-[#999]" />
            )}
        </button>
    );
}
