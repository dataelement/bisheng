import { Outlined } from 'bisheng-icons';
import { Tooltip } from '@bisheng/ui';
import { DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { useIsClipped } from '~/hooks/useIsClipped';
import { cn } from '~/utils';
import type { SkillRecord } from './types';

interface SkillMenuRowProps {
  skill: SkillRecord;
  checked: boolean;
  onToggle: (skill: SkillRecord) => void;
}

export function SkillMenuRow({ skill, checked, onToggle }: SkillMenuRowProps) {
  const localize = useLocalize();
  const [nameRef, nameClipped] = useIsClipped<HTMLParagraphElement>(skill.displayName);
  const [descriptionRef, descriptionClipped] = useIsClipped<HTMLParagraphElement>(skill.description);
  const from = localize(skill.source === 'personal' ? 'com_skill_center_from_me' : 'com_skill_center_from_platform');

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
        onSelect={(event) => {
          event.preventDefault();
          onToggle(skill);
        }}
        className={cn(
          'flex cursor-pointer items-start rounded-lg px-2 py-[5px] outline-none transition-colors data-[highlighted]:bg-fill-2 focus:bg-fill-2',
          checked && 'bg-blue-500/[0.07]',
        )}
      >
        <div className="min-w-0 flex-1">
          <p ref={nameRef} className="truncate text-body-sm font-normal text-text-1">{skill.displayName}</p>
          <p ref={descriptionRef} className="truncate text-caption font-normal text-text-3">
            {from}
            {skill.description ? ` · ${skill.description}` : ''}
          </p>
        </div>
        {checked && <Outlined.Check size={14} className="mt-1 shrink-0 text-blue-500" />}
      </DropdownMenuItem>
    </Tooltip>
  );
}
