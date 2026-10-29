import { DropdownMenuItem } from '~/components/ui';
import { ComposerMenuText } from '~/components/ui/ComposerMenuText';
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
      <ComposerMenuText name={skill.displayName} description={skill.description} />
    </DropdownMenuItem>
  );
}
