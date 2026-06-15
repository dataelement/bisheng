/**
 * F035 Track H (P3): generic collapsible step row (spec §3).
 * Default open while running, auto-collapses on completion — unless the user
 * toggled manually, in which case the manual choice wins.
 */
import { Outlined } from 'bisheng-icons';
import { ChevronDown, ChevronRight, Wrench } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { cn } from '~/utils';

/** Shared spinner glyph for in-progress steps. */
export function RunningSpinner() {
    return <Outlined.Loading size={14} className="animate-spin text-primary" />;
}

/** Map a step/tool name to its leading icon (completed state). */
export function stepTypeIcon(name?: string) {
    const n = (name || '').toLowerCase();
    const cls = 'text-[#333]';
    if (/agent|subagent/.test(n)) return <Outlined.PeopleRound size={14} className={cls} />;
    if (/knowledge|knowledge_base|space|retrieval|recall|检索|知识/.test(n)) return <Outlined.BookOpenText size={14} className={cls} />;
    if (/think|reason|思考/.test(n)) return <Outlined.Bulb size={14} className={cls} />;
    if (/research|调研/.test(n)) return <Outlined.Dashboard size={14} className={cls} />;
    return <Wrench size={14} className={cls} />; // default
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
        <div className={cn('w-full mb-6', className)}>
            <button
                type="button"
                className={cn(
                    'group flex w-full items-center gap-2 rounded-lg text-left text-sm',
                    collapsible ? 'cursor-pointer hover:bg-black/[0.03]' : 'cursor-default',
                )}
                onClick={() => collapsible && setManualOpen(!open)}
            >
                {/* relative z-10 + bg-white so the icon "breaks" the timeline spine
                    (drawn in StepList) into discrete nodes and sits above it. */}
                <span className="relative z-10 flex size-4 shrink-0 items-center justify-center bg-white">{icon}</span>
                {/* min-w-0 (not flex-1) so the chevron sits right after the title
                    text instead of being pushed to the far right; long titles
                    still shrink + truncate. */}
                <span className={cn('min-w-0 truncate text-[#8C8C8C]', titleClassName)}>{title}</span>
                {collapsible && (
                    <span className="shrink-0 text-[#8C8C8C]">
                        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </span>
                )}
                {rightExtra}
            </button>
            {/* Expanded content: no left border; aligned with the title (ml-6 =
                icon 16 + gap 8); 8px gap from the title; 12px text. */}
            {open && <div className="ml-6 mt-2 space-y-2 pb-1 text-xs">{children}</div>}
        </div>
    );
}
