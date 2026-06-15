/**
 * F035 Track H: the "+" popup menu in the task-mode input toolbar.
 * Items (spec §1): Upload file / Task mode toggle / Add Skill (submenu with
 * the multi-select skill list).
 */
import { Check, Plus } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '~/components/ui';
import { useLocalize } from '~/hooks';
import type { TaskModeSkill } from '~/store/linsight';
import { cn } from '~/utils';
import { SkillSelector } from './SkillSelector';

interface PlusMenuProps {
    disabled?: boolean;
    /** Opens the hidden file picker (InputFiles imperative ref). */
    onUploadFile: () => void;
    taskModeActive: boolean;
    onToggleTaskMode: () => void;
    selectedSkills: TaskModeSkill[];
    onSkillsChange: (skills: TaskModeSkill[]) => void;
    /** Add-skill entry is task-mode only; daily mode hides it (unified input). */
    showAddSkill?: boolean;
}

export function PlusMenu({
    disabled = false,
    onUploadFile,
    taskModeActive,
    onToggleTaskMode,
    selectedSkills,
    onSkillsChange,
    showAddSkill = true,
}: PlusMenuProps) {
    const localize = useLocalize();

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild disabled={disabled}>
                <button
                    type="button"
                    aria-label={localize('com_ui_upload_files')}
                    className={cn(
                        'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[#4E5969] outline-none transition-colors hover:bg-black/5',
                        disabled && 'cursor-not-allowed opacity-50',
                    )}
                >
                    <Plus size={18} strokeWidth={1.5} />
                </button>
            </DropdownMenuTrigger>

            <DropdownMenuContent
                align="start"
                className="flex w-[200px] flex-col gap-0 rounded-2xl border-slate-100 p-1.5 shadow-xl"
            >
                {/* Upload file (icon: shared daily-mode `link` asset) */}
                <DropdownMenuItem
                    onSelect={() => onUploadFile()}
                    className="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-1.5 outline-none"
                >
                    <img
                        src={`${__APP_ENV__.BASE_URL || ''}/assets/channel/link.svg`}
                        className="size-4 shrink-0"
                        alt=""
                    />
                    <span className="text-[14px] font-normal text-slate-700">
                        {localize('com_ui_upload_files')}
                    </span>
                </DropdownMenuItem>

                {/* Divider between upload and the mode entries (spec §1) */}
                <div className="my-1 h-px bg-slate-100" />

                {/* Task mode toggle */}
                <DropdownMenuItem
                    onSelect={() => onToggleTaskMode()}
                    className="flex cursor-pointer items-center gap-3 rounded-xl px-2 py-1.5 outline-none"
                >
                    <Outlined.Binoculars size={16} className={cn(taskModeActive ? 'text-blue-600' : 'text-slate-600')} />
                    <span
                        className={cn(
                            'flex-1 text-[14px] font-normal',
                            taskModeActive ? 'text-blue-600' : 'text-slate-700',
                        )}
                    >
                        {localize('com_linsight_task_mode')}
                    </span>
                    {taskModeActive && <Check size={14} className="text-blue-600" />}
                </DropdownMenuItem>

                {/* Add Skill submenu — task mode only (hidden in daily mode) */}
                {showAddSkill && (
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger
                            className={cn(
                                'mt-0.5 flex cursor-pointer items-center justify-between rounded-xl px-2 py-1.5 outline-none',
                                '!bg-transparent hover:!bg-transparent focus:!bg-transparent',
                            )}
                        >
                            <div className="flex items-center gap-3">
                                <div className="relative">
                                    <Outlined.Newspaper size={16} className="text-slate-600" />
                                    {selectedSkills.length > 0 && (
                                        <span className="absolute -right-1 -top-1 size-2.5 rounded-full border-2 border-white bg-blue-500" />
                                    )}
                                </div>
                                <span className="text-[14px] font-normal text-slate-700">
                                    {localize('com_linsight_add_skill')}
                                </span>
                            </div>
                            {/* ChevronRight is rendered by DropdownMenuSubTrigger itself */}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="ml-2 flex w-[280px] flex-col overflow-hidden rounded-2xl border-slate-100 bg-white p-2 shadow-2xl">
                            <SkillSelector selected={selectedSkills} onChange={onSkillsChange} />
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
