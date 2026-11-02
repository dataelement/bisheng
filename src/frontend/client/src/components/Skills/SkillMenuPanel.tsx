import { Outlined } from 'bisheng-icons';
import { DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { SkillSelector } from '~/components/Linsight/Input/SkillSelector';
import type { TaskModeSkill } from '~/store/linsight';

interface SkillMenuPanelProps {
  onBack?: () => void;
  selected: TaskModeSkill[];
  onChange: (skills: TaskModeSkill[]) => void;
}

/** Composer menus select executable skills into the owning input's state. */
export function SkillMenuPanel({ onBack, selected, onChange }: SkillMenuPanelProps) {
  const localize = useLocalize();
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {onBack && <DropdownMenuItem onSelect={(event) => { event.preventDefault(); onBack(); }} className="shrink-0 cursor-pointer gap-2 rounded-lg px-2 py-2 text-body-sm text-text-1">
        <Outlined.ArrowLeft className="size-4" />{localize('com_skill_center_menu')}
      </DropdownMenuItem>}
      <SkillSelector selected={selected} onChange={onChange} layout="command" />
    </div>
  );
}
