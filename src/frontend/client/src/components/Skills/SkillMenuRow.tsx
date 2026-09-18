import { Tooltip } from '@bisheng/ui';
import { DropdownMenuItem } from '~/components/ui';
import { useIsClipped } from '~/hooks/useIsClipped';
import type { CenterSkill } from './types';

interface SkillMenuRowProps {
  skill: CenterSkill;
  onSelect: () => void;
}

export function SkillMenuRow({ skill, onSelect }: SkillMenuRowProps) {
  const [nameRef, nameClipped] = useIsClipped<HTMLParagraphElement>(skill.displayName);
  const [descriptionRef, descriptionClipped] = useIsClipped<HTMLParagraphElement>(skill.description);

  return (
    <Tooltip
      side="right"
      align="start"
      disabled={!nameClipped && !descriptionClipped}
      contentClassName="whitespace-pre-wrap"
      content={<>
        <p className="font-medium">{skill.displayName}</p>
        {skill.description && <p className="mt-1 text-caption text-white/80">{skill.description}</p>}
      </>}
    >
      <DropdownMenuItem
        onSelect={onSelect}
        className="flex cursor-pointer items-start rounded-lg px-2 py-[5px] outline-none transition-colors data-[highlighted]:bg-fill-2 focus:bg-fill-2"
      >
        <div className="min-w-0 flex-1">
          <p ref={nameRef} className="truncate text-body-sm font-normal text-text-1">{skill.displayName}</p>
          {skill.description && <p ref={descriptionRef} className="truncate text-caption font-normal text-text-3">{skill.description}</p>}
        </div>
      </DropdownMenuItem>
    </Tooltip>
  );
}
