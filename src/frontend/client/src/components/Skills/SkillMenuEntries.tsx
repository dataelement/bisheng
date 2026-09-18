import { lazy, Suspense, useState, type ReactNode } from 'react';
import { Outlined } from 'bisheng-icons';
import { PlusMenuSub } from '~/components/Chat/Input/PlusMenuSub';
import { DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { skillCenterPreviewEnabled } from './types';
import { SkillMenuPanel } from './SkillMenuPanel';

const UploadDialog = lazy(() => import('./SkillUploadDialog').then((module) => ({ default: module.SkillUploadDialog })));

interface SkillUploadHostProps { children: (openUpload: () => void) => ReactNode }

/** Keep the modal outside the menu portal so closing a menu cannot unmount it. */
export function SkillUploadHost({ children }: SkillUploadHostProps) {
  const [open, setOpen] = useState(false);
  return <>
    {children(() => setOpen(true))}
    {open && skillCenterPreviewEnabled && <Suspense fallback={null}><UploadDialog open onOpenChange={setOpen} /></Suspense>}
  </>;
}

interface SkillMenuEntriesProps {
  onUpload: () => void;
  onOpenMobile?: () => void;
}

export function SkillMenuEntries({ onUpload, onOpenMobile }: SkillMenuEntriesProps) {
  const localize = useLocalize();
  if (!skillCenterPreviewEnabled) return null;
  const icon = <Outlined.Newspaper size={16} className="text-text-2" />;
  const label = localize('com_skill_center_menu');
  if (onOpenMobile) return (
    <DropdownMenuItem onSelect={(event) => { event.preventDefault(); onOpenMobile(); }} className="flex h-8 cursor-pointer items-center justify-between gap-2 rounded-lg px-2 outline-none">
      <div className="flex min-w-0 items-center gap-2">
        {icon}<span className="truncate text-[14px] font-normal text-slate-700">{label}</span>
      </div>
      <Outlined.Right className="size-4 shrink-0 text-slate-400" />
    </DropdownMenuItem>
  );
  // The panel ends in two menu rows rather than a scroll list, so it keeps its bottom padding.
  return (
    <PlusMenuSub icon={icon} label={label} panelClassName="w-[280px] max-w-[calc(100vw-24px)] gap-0 pb-3">
      <SkillMenuPanel onUpload={onUpload} />
    </PlusMenuSub>
  );
}
