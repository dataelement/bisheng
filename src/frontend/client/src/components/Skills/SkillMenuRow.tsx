import { DropdownMenuItem } from '~/components/ui';
import type { CenterSkill } from './types';

interface SkillMenuRowProps {
  skill: CenterSkill;
  onSelect: () => void;
}

export function SkillMenuRow({ skill, onSelect }: SkillMenuRowProps) {
  return (
    <DropdownMenuItem
      onSelect={onSelect}
      className="flex cursor-pointer items-start rounded-lg px-2 py-[5px] outline-none transition-colors data-[highlighted]:bg-fill-2 focus:bg-fill-2"
    >
      <div className="skill-menu-text min-w-0 flex-1">
        <p className="skill-menu-name dsh-command-name text-text-1">{skill.displayName}</p>
        {skill.description && <p className="skill-menu-description dsh-command-description">{skill.description}</p>}
      </div>
    </DropdownMenuItem>
  );
}
