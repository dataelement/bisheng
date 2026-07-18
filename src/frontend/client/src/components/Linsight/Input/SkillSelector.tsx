/**
 * F035 Track H: multi-select list of enabled skills, rendered inside the
 * "+" menu's "Add Skill" submenu. Data: GET /api/v1/linsight/skill/selectable
 * (enabled skills only, plain login auth). Selections become chips above the
 * textarea; only checked skills are sent with the submission. Supports keyword
 * search over display name + description.
 */
import { Check, Loader2, SearchIcon } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSelectableSkills } from '~/api/linsight';
import { DropdownMenuItem, Input } from '~/components/ui';
import { useLocalize } from '~/hooks';
import type { TaskModeSkill } from '~/store/linsight';
import { cn } from '~/utils';

interface SkillSelectorProps {
    selected: TaskModeSkill[];
    onChange: (skills: TaskModeSkill[]) => void;
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

    const handleToggle = (skill: TaskModeSkill) => {
        const exists = selected.some((s) => s.name === skill.name);
        onChange(
            exists
                ? selected.filter((s) => s.name !== skill.name)
                : [...selected, { name: skill.name, display_name: skill.display_name, description: skill.description }],
        );
    };

    return (
        <div className="flex min-h-0 flex-1 flex-col gap-1">
            {/* Panel title — mirrors the knowledge panel header for visual consistency */}
            <p className="mb-1 shrink-0 px-2 py-[5px] text-[14px] font-medium leading-[22px] text-[#1A1A1A]">
                {localize('com_linsight_skill_title')}
            </p>

            {/* Search — stopPropagation so typing isn't hijacked by the Radix menu's type-ahead */}
            <div className="relative shrink-0">
                <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                <Input
                    className="h-[28px] rounded-[6px] border border-[#ECECEC] bg-white pl-8 text-sm focus-visible:ring-1 focus-visible:ring-blue-500/20"
                    placeholder={localize('com_linsight_skill_search')}
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => e.stopPropagation()}
                />
            </div>

            {/* List */}
            {isFetching && skills.length === 0 ? (
                <div className="flex justify-center py-4">
                    <Loader2 size={16} className="animate-spin text-slate-300" />
                </div>
            ) : filtered.length === 0 ? (
                <div className="px-2 py-4 text-center text-xs text-slate-400">
                    {localize('com_linsight_skill_empty')}
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
                        className="scrollbar-os flex min-h-0 flex-1 flex-col gap-0 overflow-y-auto pb-2"
                        onScroll={updateScrollIndicators}
                    >
                    {filtered.map((skill) => {
                        const isChecked = selected.some((s) => s.name === skill.name);
                        return (
                            <DropdownMenuItem
                                key={skill.name}
                                onSelect={(e) => {
                                    e.preventDefault();
                                    handleToggle(skill);
                                }}
                                className="flex cursor-pointer items-start gap-2 rounded-[6px] px-2 py-[5px] outline-none transition-colors data-[highlighted]:bg-[#f2f3f5] focus:bg-[#f2f3f5]"
                            >
                                <div
                                    className={cn(
                                        'mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border transition-colors',
                                        isChecked ? 'border-blue-600 bg-blue-600' : 'border-slate-300 bg-white',
                                    )}
                                >
                                    {isChecked && <Check size={12} className="stroke-[3] text-white" />}
                                </div>
                                <div className="min-w-0 flex-1">
                                    <p className="truncate text-[14px] leading-5 text-slate-700">{skill.display_name}</p>
                                    {skill.description && (
                                        <p className="line-clamp-2 text-[12px] leading-4 text-[#999]">{skill.description}</p>
                                    )}
                                </div>
                            </DropdownMenuItem>
                        );
                    })}
                    </div>
                </div>
            )}
        </div>
    );
}
