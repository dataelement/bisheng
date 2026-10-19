import { useNavigate } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from '~/components/ui';
import { useLocalize } from '~/hooks';
import type { TaskModeSkill } from '~/store/linsight';
import { useSkillCenter } from './useSkillCenter';
import { skillCenterPath, type SkillRecord } from './types';
import { SkillMenuRow } from './SkillMenuRow';

interface SkillMenuPanelProps {
  selected: TaskModeSkill[];
  onChange: (skills: TaskModeSkill[]) => void;
  onUpload: () => void;
  onBack?: () => void;
}

function toTaskSkill(skill: SkillRecord): TaskModeSkill {
  return { id: skill.id, name: skill.name, display_name: skill.displayName, description: skill.description };
}

export function SkillMenuPanel({ selected, onChange, onUpload, onBack }: SkillMenuPanelProps) {
  const localize = useLocalize();
  const navigate = useNavigate();
  const { personal, platform } = useSkillCenter();
  // Both enabled copies stay visible. The task copy later keeps the personal bundle.
  const skills = [...(personal.data ?? []), ...(platform.data ?? [])]
    .filter((skill) => skill.enabled)
    .sort((left, right) => left.displayName.localeCompare(right.displayName) || left.id - right.id);
  const loading = personal.isLoading || platform.isLoading;
  const failed = personal.isError || platform.isError;
  const toggle = (skill: SkillRecord) => {
    const checked = selected.some((item) => item.id === skill.id);
    onChange(checked ? selected.filter((item) => item.id !== skill.id) : [...selected, toTaskSkill(skill)]);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {onBack && <DropdownMenuItem onSelect={(event) => { event.preventDefault(); onBack(); }} className="shrink-0 cursor-pointer gap-2 rounded-lg px-2 py-2 text-body-sm text-text-1">
        <Outlined.ArrowLeft className="size-4" />{localize('com_skill_center_menu')}
      </DropdownMenuItem>}
      <DropdownMenuLabel className="shrink-0 px-2 pb-1 pt-2 text-caption font-normal text-text-3">{localize('com_skill_center_menu_available')}</DropdownMenuLabel>
      <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto overscroll-contain pb-1">
        {loading && skills.length === 0 ? <p role="status" className="px-2 py-5 text-body-sm text-text-3">{localize('com_skill_center_loading')}</p> : skills.length ? skills.map((skill) => (
          <SkillMenuRow
            key={skill.id}
            skill={skill}
            checked={selected.some((item) => item.id === skill.id)}
            onToggle={toggle}
          />
        )) : !failed && <p className="px-2 py-5 text-body-sm text-text-3">{localize('com_skill_center_empty')}</p>}
        {failed && <div className="px-2 py-2">
          <p role="alert" className="text-caption text-text-3">{localize('com_skill_center_load_failed')}</p>
          <DropdownMenuItem disabled={loading} onSelect={(event) => { event.preventDefault(); void personal.refetch(); }} className="mt-1 cursor-pointer rounded-lg text-body-sm text-text-1">{localize('com_skill_center_retry')}</DropdownMenuItem>
        </div>}
      </div>
      <DropdownMenuSeparator className="shrink-0" />
      <DropdownMenuItem onSelect={onUpload} className="h-8 shrink-0 cursor-pointer gap-2 rounded-lg px-2 text-body-sm font-normal text-text-1">
        <Outlined.Upload className="size-4 text-text-2" />{localize('com_skill_center_upload')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => navigate(skillCenterPath)} className="h-8 shrink-0 cursor-pointer gap-2 rounded-lg px-2 text-body-sm font-normal text-text-1">
        <Outlined.Setting className="size-4 text-text-2" />{localize('com_skill_center_manage')}
      </DropdownMenuItem>
    </div>
  );
}
