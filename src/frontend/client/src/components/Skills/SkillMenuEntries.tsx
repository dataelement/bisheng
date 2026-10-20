import { Outlined } from 'bisheng-icons';
import { ComposerSubmenu } from '~/components/Chat/Input/ComposerSubmenu';
import { PlusMenuSub } from '~/components/Chat/Input/PlusMenuSub';
import { DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { skillCenterPreviewEnabled } from './types';
import { SkillMenuPanel } from './SkillMenuPanel';

interface SkillMenuEntriesProps {
  onOpenMobile?: () => void;
  inline?: boolean;
}

export function SkillMenuEntries({ onOpenMobile, inline }: SkillMenuEntriesProps) {
  const localize = useLocalize();
  if (!skillCenterPreviewEnabled) return null;
  const icon = <Outlined.Skill size={16} className="text-text-2" />;
  const label = localize('com_skill_center_menu');
  if (inline) return <ComposerSubmenu icon={icon} label={label}>
    <SkillMenuPanel />
  </ComposerSubmenu>;
  if (onOpenMobile) return (
    <DropdownMenuItem onSelect={(event) => { event.preventDefault(); onOpenMobile(); }} className="flex h-8 cursor-pointer items-center justify-between gap-2 rounded-lg px-2 outline-none">
      <div className="flex min-w-0 items-center gap-2">
        {icon}<span className="truncate text-[14px] font-normal text-slate-700">{label}</span>
      </div>
      <Outlined.Right className="size-4 shrink-0 text-slate-400" />
    </DropdownMenuItem>
  );
  return (
    <PlusMenuSub icon={icon} label={label} panelClassName="w-[280px] max-w-[calc(100vw-24px)] gap-0 pb-1">
      <SkillMenuPanel />
    </PlusMenuSub>
  );
}
