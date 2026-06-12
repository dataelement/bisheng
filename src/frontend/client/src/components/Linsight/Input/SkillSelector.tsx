/**
 * F035 Track H: multi-select list of enabled skills, rendered inside the
 * "+" menu's "Add Skill" submenu. Data: GET /api/v1/linsight/skill/selectable
 * (enabled skills only, plain login auth). Selections become chips above the
 * textarea; only checked skills are sent with the submission.
 */
import { Check, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { getSelectableSkills } from '~/api/linsight';
import { DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import type { TaskModeSkill } from '~/store/linsight';
import { cn } from '~/utils';

interface SkillSelectorProps {
    selected: TaskModeSkill[];
    onChange: (skills: TaskModeSkill[]) => void;
}

export function SkillSelector({ selected, onChange }: SkillSelectorProps) {
    const localize = useLocalize();
    const { data: skills = [], isFetching } = useQuery({
        queryKey: ['linsightSelectableSkills'],
        queryFn: getSelectableSkills,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
    });

    const handleToggle = (skill: TaskModeSkill) => {
        const exists = selected.some((s) => s.name === skill.name);
        onChange(
            exists
                ? selected.filter((s) => s.name !== skill.name)
                : [...selected, { name: skill.name, display_name: skill.display_name, description: skill.description }],
        );
    };

    if (isFetching && skills.length === 0) {
        return (
            <div className="flex justify-center py-4">
                <Loader2 size={16} className="animate-spin text-slate-300" />
            </div>
        );
    }

    if (skills.length === 0) {
        return (
            <div className="px-2 py-4 text-center text-xs text-slate-400">
                {localize('com_linsight_skill_empty')}
            </div>
        );
    }

    return (
        <div className="flex max-h-[320px] flex-col gap-0.5 overflow-y-auto">
            {skills.map((skill) => {
                const isChecked = selected.some((s) => s.name === skill.name);
                return (
                    <DropdownMenuItem
                        key={skill.name}
                        onSelect={(e) => {
                            e.preventDefault();
                            handleToggle(skill);
                        }}
                        className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2 py-2 outline-none hover:bg-slate-50 focus:bg-slate-50"
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
                            <p className="truncate text-[13px] leading-5 text-slate-700">{skill.display_name}</p>
                            {skill.description && (
                                <p className="line-clamp-2 text-xs leading-4 text-slate-400">{skill.description}</p>
                            )}
                        </div>
                    </DropdownMenuItem>
                );
            })}
        </div>
    );
}
