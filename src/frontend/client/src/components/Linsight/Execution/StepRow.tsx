/**
 * F035 Track H (P3): generic collapsible step row (spec §3).
 * Default open while running, auto-collapses on completion — unless the user
 * toggled manually, in which case the manual choice wins.
 */
import { Outlined } from 'bisheng-icons';
import { Wrench } from 'lucide-react';
import { createContext, useContext, useState, type ReactNode } from 'react';
import { cn } from '~/utils';

/** Step-row nesting depth. Top-level rows (depth 0 — the outer flow / big tasks)
 *  render NO connector line; only nested sub-steps (depth ≥ 1, rendered inside an
 *  expanded parent) get the rail. Provided automatically by each StepRow around
 *  its children, so no prop-plumbing through the row components is needed. */
const StepDepthContext = createContext(0);

/** Shared spinner glyph for in-progress steps. */
export function RunningSpinner() {
    return <Outlined.Loading size={16} className="animate-spin text-primary" />;
}

/** Map a step/tool name to its leading icon (completed state). */
export function stepTypeIcon(name?: string, size = 16) {
    const n = (name || '').toLowerCase();
    const cls = 'text-[#333]';
    if (/agent|subagent/.test(n)) return <Outlined.PeopleRound size={size} className={cls} />;
    if (/knowledge|knowledge_base|space|retrieval|recall|检索|知识/.test(n)) return <Outlined.BookOpenText size={size} className={cls} />;
    if (/think|reason|思考/.test(n)) return <Outlined.Bulb size={size} className={cls} />;
    if (/research|调研/.test(n)) return <Outlined.Dashboard size={size} className={cls} />;
    if (/web[_\s-]?search|websearch|联网|网页|网络搜索/.test(n)) return <Outlined.Earth size={size} className={cls} />;
    if (/write|edit|撰写|编写|写入/.test(n)) return <Outlined.Write size={size} className={cls} />;
    return <Wrench size={size} className={cls} />; // default
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

/** icon / title may depend on the open state (e.g. collapsed shows a running
 *  sub-step summary, expanded shows the node's own title). */
type OpenAware<T> = T | ((open: boolean) => T);

interface StepRowProps {
    /** leading icon (status glyph / tool icon) */
    icon: OpenAware<ReactNode>;
    /** row title content */
    title: OpenAware<ReactNode>;
    /** optional content rendered when expanded; row is not collapsible without it */
    children?: ReactNode;
    /** running steps default to expanded; completed default to collapsed */
    running?: boolean;
    /** override the auto open-while-running rule for the initial state */
    defaultOpen?: boolean;
    /** extra content pinned to the right side of the header */
    rightExtra?: ReactNode;
    className?: string;
    titleClassName?: string;
}

export function StepRow({ icon, title, children, running = false, defaultOpen, rightExtra, className, titleClassName }: StepRowProps) {
    // null = follow auto rule (open while running); boolean = manual override
    const depth = useContext(StepDepthContext);
    const [manualOpen, setManualOpen] = useState<boolean | null>(null);
    const collapsible = children != null;
    const open = collapsible && (manualOpen ?? defaultOpen ?? running);
    // Connector only for nested sub-steps; the outer/top-level rows show none.
    const showConnector = open && depth > 0;
    const renderedIcon = typeof icon === 'function' ? icon(open) : icon;
    const renderedTitle = typeof title === 'function' ? title(open) : title;

    return (
        /* last:mb-0 only for nested sub-steps (depth > 0) — drops the trailing
           gap inside an expanded task. Flow-level rows (depth 0) keep mb-6 so the
           last session step doesn't collide with the task list that follows. */
        <div className={cn('flex w-full min-w-0 gap-2 mb-6', depth > 0 && 'last:mb-0', className)}>
            {/* Left rail: status icon + a connector that renders ONLY while THIS
                node is expanded, so the timeline is per-node (one segment beside
                an open node) rather than a single continuous spine — mirrors the
                daily "思考内容" rail. flex-1 makes the segment span the node's body. */}
            <div className="flex shrink-0 flex-col items-center gap-1 self-stretch">
                {/* icon box height == title line-height (text-sm → 20px) so the icon
                    is centered on the first text line instead of a hand-tuned offset. */}
                <span className="flex h-5 w-4 shrink-0 items-center justify-center">{renderedIcon}</span>
                {showConnector && <div aria-hidden className="w-px flex-1 bg-[#E0E0E0]" />}
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
                <button
                    type="button"
                    className={cn(
                        'flex w-fit max-w-full items-center gap-1 text-left text-sm',
                        collapsible ? 'group cursor-pointer' : 'cursor-default',
                    )}
                    onClick={() => collapsible && setManualOpen(!open)}
                >
                    {/* hover recolors only the title to the body color (no full-row
                        gray box), matching the daily "思考内容" trigger. group is set
                        on the button only when collapsible, so static rows don't get
                        a false clickable affordance. min-w-0 (not flex-1) keeps the
                        chevron right after the title; long titles truncate. */}
                    <span className={cn('min-w-0 truncate text-[#8C8C8C] transition-colors group-hover:text-[#212121]', titleClassName)}>{renderedTitle}</span>
                    {collapsible && (
                        <span className="shrink-0 text-[#8C8C8C] transition-colors group-hover:text-[#212121]">
                            {/* single chevron rotates right→down, matching the daily
                                "深度思考" toggle instead of swapping two glyphs */}
                            <Outlined.Down
                                size={16}
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
                            <StepDepthContext.Provider value={depth + 1}>
                                <div className="mt-4 space-y-2 pb-1 text-xs">{children}</div>
                            </StepDepthContext.Provider>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
