/**
 * F035 Track H: task-mode toggle button shown in the input toolbar.
 * - inactive: plain text button (daily chat entry — navigates to /linsight)
 * - active: blue highlighted; hovering swaps the icon for an "x" so the user
 *   can explicitly exit task mode (spec §1, fig.2). No auto-exit on messages.
 */
import { Glasses, X } from 'lucide-react';
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
                'flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-xs font-normal transition-colors outline-none',
                active
                    ? 'bg-blue-50 text-blue-600 hover:bg-blue-100'
                    : 'text-[#4E5969] hover:bg-black/5',
                disabled && 'cursor-not-allowed opacity-50',
            )}
        >
            {showExit ? <X size={16} /> : <Glasses size={16} />}
            <span>{localize('com_linsight_task_mode')}</span>
        </button>
    );
}
