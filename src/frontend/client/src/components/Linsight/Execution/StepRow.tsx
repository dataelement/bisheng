/**
 * F035 Track H (P3): generic collapsible step row (spec §3).
 * Default open while running, auto-collapses on completion — unless the user
 * toggled manually, in which case the manual choice wins.
 */
import { ChevronDown, ChevronRight, LoaderCircle } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { cn } from '~/utils';

/** Shared spinner glyph for in-progress steps. */
export function RunningSpinner() {
    return <LoaderCircle size={14} className="animate-spin text-blue-500" />;
}

/** Shared style for expanded detail text blocks. */
export const detailTextCls = 'whitespace-pre-wrap break-words text-xs leading-5 text-gray-500';

/** Pretty-print step params defensively; never throws on odd payloads. */
export function formatStepParams(params: Record<string, any> | null): string {
    if (!params || !Object.keys(params).length) return '';
    try {
        return Object.entries(params)
            .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
            .join('\n');
    } catch {
        return String(params);
    }
}

interface StepRowProps {
    /** leading icon (status glyph / tool icon) */
    icon: ReactNode;
    /** row title content */
    title: ReactNode;
    /** optional content rendered when expanded; row is not collapsible without it */
    children?: ReactNode;
    /** running steps default to expanded; completed default to collapsed */
    running?: boolean;
    /** extra content pinned to the right side of the header */
    rightExtra?: ReactNode;
    className?: string;
    titleClassName?: string;
}

export function StepRow({ icon, title, children, running = false, rightExtra, className, titleClassName }: StepRowProps) {
    // null = follow auto rule (open while running); boolean = manual override
    const [manualOpen, setManualOpen] = useState<boolean | null>(null);
    const collapsible = children != null;
    const open = collapsible && (manualOpen ?? running);

    return (
        <div className={cn('w-full', className)}>
            <button
                type="button"
                className={cn(
                    'group flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm',
                    collapsible ? 'cursor-pointer hover:bg-black/[0.03]' : 'cursor-default',
                )}
                onClick={() => collapsible && setManualOpen(!open)}
            >
                <span className="flex size-4 shrink-0 items-center justify-center">{icon}</span>
                <span className={cn('min-w-0 flex-1 truncate text-gray-700', titleClassName)}>{title}</span>
                {rightExtra}
                {collapsible && (
                    <span className="shrink-0 text-gray-400">
                        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </span>
                )}
            </button>
            {open && <div className="ml-6 mt-0.5 border-l border-gray-200 pb-1 pl-3">{children}</div>}
        </div>
    );
}
