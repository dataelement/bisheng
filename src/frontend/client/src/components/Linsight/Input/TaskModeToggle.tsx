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
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';

interface TaskModeToggleProps {
    active: boolean;
    disabled?: boolean;
    onClick: () => void;
}

export function TaskModeToggle({ active, disabled = false, onClick }: TaskModeToggleProps) {
    const localize = useLocalize();
    const [hovered, setHovered] = useState(false);
    const showExit = active && hovered;

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
                'flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-[13px] font-normal transition-colors outline-none hover:bg-[#E0E6FF]',
                active ? 'text-blue-600' : 'text-[#4E5969]',
                disabled && 'cursor-not-allowed opacity-50',
            )}
        >
            {showExit ? (
                <X size={16} className="text-blue-600" />
            ) : (
                <Outlined.Binoculars size={16} className={active ? 'text-blue-600' : 'text-[#4E5969]'} />
            )}
            {/* Mobile: collapse to icon only to save horizontal space in the
                input toolbar, matching the knowledge/tools selectors. */}
            <span className="touch-mobile:hidden">{localize('com_linsight_task_mode')}</span>
            {/* Mobile + active: persistent exit "x" standing in for the other
                selectors' chevron — same size/color/gap as their down icon
                (size 16, #999). Desktop keeps the hover-swap affordance above. */}
            {active && (
                <X size={16} className="hidden shrink-0 text-[#999] touch-mobile:block" />
            )}
        </button>
    );
}
