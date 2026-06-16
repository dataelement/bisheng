/**
 * F035 Track H (P3): generic collapsible step row (spec §3).
 * Default open while running, auto-collapses on completion — unless the user
 * toggled manually, in which case the manual choice wins.
 */
import { Outlined } from 'bisheng-icons';
import { ChevronDown, Wrench } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { cn } from '~/utils';

/** Shared spinner glyph for in-progress steps. */
export function RunningSpinner() {
    return <Outlined.Loading size={16} className="animate-spin text-primary" />;
}

/** Map a step/tool name to its leading icon (completed state). */
export function stepTypeIcon(name?: string) {
    const n = (name || '').toLowerCase();
    const cls = 'text-[#333]';
    if (/agent|subagent/.test(n)) return <Outlined.PeopleRound size={16} className={cls} />;
    if (/knowledge|knowledge_base|space|retrieval|recall|检索|知识/.test(n)) return <Outlined.BookOpenText size={16} className={cls} />;
    if (/think|reason|思考/.test(n)) return <Outlined.Bulb size={16} className={cls} />;
    if (/research|调研/.test(n)) return <Outlined.Dashboard size={16} className={cls} />;
    if (/web[_\s-]?search|websearch|联网|网页|网络搜索/.test(n)) return <Outlined.Earth size={16} className={cls} />;
    return <Wrench size={16} className={cls} />; // default
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
        <div className={cn('flex w-full min-w-0 gap-2 mb-6', className)}>
            {/* Left rail: status icon + a connector that renders ONLY while THIS
                node is expanded, so the timeline is per-node (one segment beside
                an open node) rather than a single continuous spine — mirrors the
                daily "思考内容" rail. flex-1 makes the segment span the node's body. */}
            <div className="flex shrink-0 flex-col items-center gap-1 self-stretch pt-[3px]">
                <span className="flex size-4 shrink-0 items-center justify-center">{icon}</span>
                {open && <div aria-hidden className="w-px flex-1 bg-[#E0E0E0]" />}
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
                <button
                    type="button"
                    className={cn(
                        'flex w-fit max-w-full items-center gap-2 text-left text-sm',
                        collapsible ? 'group cursor-pointer' : 'cursor-default',
                    )}
                    onClick={() => collapsible && setManualOpen(!open)}
                >
                    {/* hover recolors only the title to the body color (no full-row
                        gray box), matching the daily "思考内容" trigger. group is set
                        on the button only when collapsible, so static rows don't get
                        a false clickable affordance. min-w-0 (not flex-1) keeps the
                        chevron right after the title; long titles truncate. */}
                    <span className={cn('min-w-0 truncate text-[#8C8C8C] transition-colors group-hover:text-[#212121]', titleClassName)}>{title}</span>
                    {collapsible && (
                        <span className="shrink-0 text-[#8C8C8C] transition-colors group-hover:text-[#212121]">
                            {/* single chevron rotates right→down, matching the daily
                                "深度思考" toggle instead of swapping two glyphs */}
                            <ChevronDown
                                size={14}
                                className={cn('transform-gpu transition-transform duration-200', !open && '-rotate-90')}
                            />
                        </span>
                    )}
                    {rightExtra}
                </button>
                {/* Expanded content: grid-rows 0fr→1fr animates open/close smoothly
                    (same technique as the daily "深度思考" module). The left rail
                    supplies the indent, so no extra left margin here. */}
                {collapsible && (
                    <div
                        className="grid transition-all duration-300 ease-out"
                        style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
                    >
                        <div className="min-h-0 overflow-hidden">
                            <div className="mt-2 space-y-2 pb-1 text-xs">{children}</div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
