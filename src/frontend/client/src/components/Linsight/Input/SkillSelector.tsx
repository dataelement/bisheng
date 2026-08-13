/**
 * F035 Track H: multi-select list of enabled skills, rendered inside the
 * "+" menu's "Add Skill" submenu. Data: GET /api/v1/linsight/skill/selectable
 * (enabled skills only, plain login auth). Selections become chips above the
 * textarea; only checked skills are sent with the submission. Supports keyword
 * search over display name + description.
 */
import { Loader2 } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSelectableSkills } from '~/api/linsight';
import { DropdownMenuItem, Input } from '~/components/ui';
import { EmptyStateIllustration } from '~/components/illustrations';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize } from '~/hooks';
import type { TaskModeSkill } from '~/store/linsight';
import { cn } from '~/utils';

interface SkillSelectorProps {
    selected: TaskModeSkill[];
    onChange: (skills: TaskModeSkill[]) => void;
}

interface SkillRowProps {
    skill: TaskModeSkill;
    isChecked: boolean;
    onToggle: (skill: TaskModeSkill) => void;
}

/**
 * Whether a single-line element is actually cut off. Re-measures on resize, so
 * it keeps up with panel-width changes.
 */
function useIsClipped<T extends HTMLElement>(text?: string) {
    const ref = useRef<T | null>(null);
    const [clipped, setClipped] = useState(false);

    useLayoutEffect(() => {
        const el = ref.current;
        if (!el) {
            setClipped(false);
            return;
        }
        // +1 absorbs sub-pixel rounding, which otherwise reports a clip on text
        // that fits exactly.
        const measure = () => setClipped(el.scrollWidth > el.clientWidth + 1);
        measure();
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        return () => ro.disconnect();
    }, [text]);

    return [ref, clipped] as const;
}

/**
 * One selectable row. Name and description are each clamped to a single line;
 * the full text moves into a tooltip — but only when something actually
 * overflows, which we can only know by measuring, hence the per-row component.
 */
function SkillRow({ skill, isChecked, onToggle }: SkillRowProps) {
    const [nameRef, nameClipped] = useIsClipped<HTMLParagraphElement>(skill.display_name);
    const [descRef, descClipped] = useIsClipped<HTMLParagraphElement>(skill.description);
    const showTooltip = nameClipped || descClipped;

    return (
        // Always wrapped: rendering the tooltip conditionally would instead swap
        // the row's element type and remount it on every measure.
        <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
                <DropdownMenuItem
                    onSelect={(e) => {
                        e.preventDefault();
                        onToggle(skill);
                    }}
                    className={cn(
                        'flex cursor-pointer items-start gap-2 rounded-lg px-2 py-[5px] outline-none transition-colors',
                        'data-[highlighted]:bg-fill-2 focus:bg-fill-2',
                        // Selected rows carry the state themselves (brand tint + a
                        // trailing check) now that the leading checkbox is gone.
                        isChecked && 'bg-blue-500/[0.07] data-[highlighted]:bg-blue-500/[0.07] focus:bg-blue-500/[0.07]',
                    )}
                >
                    {/* Both lines are single-line; the full text lives in the tooltip. */}
                    <div className="min-w-0 flex-1">
                        <p
                            ref={nameRef}
                            className={cn('truncate text-[14px] leading-5', isChecked ? 'text-blue-500' : 'text-slate-700')}
                        >
                            {skill.display_name}
                        </p>
                        {skill.description && (
                            <p ref={descRef} className="truncate text-[12px] leading-4 text-text-3">
                                {skill.description}
                            </p>
                        )}
                    </div>
                    {isChecked && <Outlined.Check size={14} className="mt-1 shrink-0 text-blue-500" />}
                </DropdownMenuItem>
            </TooltipTrigger>
            {/* No content unless something is actually cut off — a tooltip that just
                repeats what is already fully visible is noise. Once it does show, it
                carries the whole row: a name-only tooltip next to a visible
                description reads as if the description were missing. */}
            {showTooltip && (
                <TooltipContent
                    side="right"
                    align="start"
                    sideOffset={8}
                    className="max-w-[260px] whitespace-normal break-words leading-[18px]"
                >
                    <p className="font-medium">{skill.display_name}</p>
                    {skill.description && (
                        <p className="mt-0.5 text-[10px] leading-[15px] text-white/70">{skill.description}</p>
                    )}
                </TooltipContent>
            )}
        </Tooltip>
    );
}

export function SkillSelector({ selected, onChange }: SkillSelectorProps) {
    const localize = useLocalize();
    const [keyword, setKeyword] = useState('');
    const { data: skills = [], isFetching } = useQuery({
        queryKey: ['linsightSelectableSkills'],
        queryFn: getSelectableSkills,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });

    const filtered = useMemo(() => {
        const kw = keyword.trim().toLowerCase();
        if (!kw) return skills;
        return skills.filter(
            (s) =>
                (s.display_name || '').toLowerCase().includes(kw) ||
                (s.description || '').toLowerCase().includes(kw),
        );
    }, [skills, keyword]);

    // Edge fades: visible only when there is content above / below the current
    // viewport. Mirrors the knowledge panel's scroll-mask behavior.
    const scrollNodeRef = useRef<HTMLDivElement | null>(null);
    const [canScrollUp, setCanScrollUp] = useState(false);
    const [canScrollDown, setCanScrollDown] = useState(false);
    const updateScrollIndicators = useCallback(() => {
        const el = scrollNodeRef.current;
        if (!el) return;
        const { scrollTop, scrollHeight, clientHeight } = el;
        setCanScrollUp(scrollTop > 0);
        setCanScrollDown(scrollTop + clientHeight < scrollHeight - 1);
    }, []);
    useEffect(() => {
        updateScrollIndicators();
    }, [filtered, updateScrollIndicators]);

    // Filtering shrinks the list, and the panel is centred on its trigger, so a
    // shrinking panel visibly jumps. Sample the unfiltered height and hold it as
    // a floor while a keyword is active.
    const listAreaRef = useRef<HTMLDivElement | null>(null);
    const [unfilteredHeight, setUnfilteredHeight] = useState<number>();
    useLayoutEffect(() => {
        if (keyword) return; // only the unfiltered list is a valid sample
        const el = listAreaRef.current;
        if (el) setUnfilteredHeight(el.getBoundingClientRect().height);
    }, [keyword, filtered.length]);

    const handleToggle = (skill: TaskModeSkill) => {
        const exists = selected.some((s) => s.name === skill.name);
        onChange(
            exists
                ? selected.filter((s) => s.name !== skill.name)
                : [...selected, { name: skill.name, display_name: skill.display_name, description: skill.description }],
        );
    };

    return (
        // gap-2: 8px between the search box and the list below it, so the first
        // row doesn't crowd the input's bottom border.
        <div className="flex min-h-0 flex-1 flex-col gap-2">
            {/* No panel heading: every surface that opens this list already
                labels it — the desktop submenu hangs off the "添加技能" row, the
                mobile drill panel has it in the back-navigation row. */}
            {/* Search — stopPropagation so typing isn't hijacked by the Radix menu's type-ahead */}
            <div className="relative shrink-0">
                {/* top nudged 1px past centre: the magnifier's ring sits above the glyph's
                    own box, so a mathematically centred icon reads high next to the text. */}
                <Outlined.Search size={14} className="absolute left-3 top-[calc(50%+1px)] -translate-y-1/2 text-slate-400" />
                <Input
                    className="h-[28px] rounded-lg border border-border-base bg-white py-0 pl-8 text-[12px] placeholder:font-normal placeholder:text-slate-400 focus-visible:border-[#DDDDDD] focus-visible:shadow-[0_0_0_2px_#F1F5F9] focus-visible:ring-0"
                    placeholder={localize('com_linsight_skill_search')}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                />
            </div>

            {/* List */}
            <div
                ref={listAreaRef}
                className="flex min-h-0 flex-1 flex-col"
                style={keyword ? { minHeight: unfilteredHeight } : undefined}
            >
            {isFetching && skills.length === 0 ? (
                <div className="flex justify-center py-4">
                    <Loader2 size={16} className="animate-spin text-slate-300" />
                </div>
            ) : filtered.length === 0 ? (
                // Centred in whatever height the list area is holding (see
                // unfilteredHeight), so searching to zero results doesn't leave
                // the copy stranded at the top of an otherwise empty panel.
                <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-1 px-2 py-4">
                    <EmptyStateIllustration grey className="size-[100px] shrink-0" />
                    <p className="text-center text-xs text-slate-400">
                        {localize('com_linsight_skill_empty')}
                    </p>
                </div>
            ) : (
                <div className="relative flex min-h-0 flex-1 flex-col">
                    {/* Top edge fade — list content dissolves into the menu surface. */}
                    <div
                        aria-hidden
                        className={cn(
                            'pointer-events-none absolute left-0 right-0 top-0 z-10 h-3 transition-opacity duration-150',
                            'bg-gradient-to-b from-white to-transparent',
                            canScrollUp ? 'opacity-100' : 'opacity-0',
                        )}
                    />
                    {/* Bottom edge fade — mirrored. */}
                    <div
                        aria-hidden
                        className={cn(
                            'pointer-events-none absolute bottom-0 left-0 right-0 z-10 h-3 transition-opacity duration-150',
                            'bg-gradient-to-t from-white to-transparent',
                            canScrollDown ? 'opacity-100' : 'opacity-0',
                        )}
                    />
                    <div
                        ref={scrollNodeRef}
                        className="scrollbar-os flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pb-3"
                        onScroll={updateScrollIndicators}
                    >
                    {filtered.map((skill, i) => (
                        <Fragment key={skill.name}>
                            {/* Hairline between rows — a standalone element rather than a
                                border on the row, so it sits centred in the 4px gutter and
                                never cuts across a selected row's tinted background. */}
                            {i > 0 && <div aria-hidden className="mx-2 h-px shrink-0 bg-slate-100" />}
                            <SkillRow
                                skill={skill}
                                isChecked={selected.some((s) => s.name === skill.name)}
                                onToggle={handleToggle}
                            />
                        </Fragment>
                    ))}
                    </div>
                </div>
            )}
            </div>
        </div>
    );
}
