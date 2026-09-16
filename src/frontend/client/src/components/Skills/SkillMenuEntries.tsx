import { lazy, Suspense, useState, type ReactNode } from 'react';
import { Outlined } from 'bisheng-icons';
import { DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '~/components/ui';
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
  const label = <span className="flex min-w-0 items-center gap-2 text-body-sm text-text-1">
    <Outlined.Newspaper className="size-4 shrink-0 text-text-2" />{localize('com_skill_center_menu')}
  </span>;
  if (onOpenMobile) return (
    <DropdownMenuItem onSelect={(event) => { event.preventDefault(); onOpenMobile(); }} className="flex cursor-pointer items-center justify-between gap-2 rounded-lg px-2 py-2">
      {label}<Outlined.Right className="size-4 shrink-0 text-text-3" />
    </DropdownMenuItem>
  );
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="cursor-pointer rounded-lg px-2 py-2">{label}</DropdownMenuSubTrigger>
      <DropdownMenuSubContent
        align="center"
        collisionPadding={12}
        className="ml-2 flex max-h-[min(440px,var(--radix-dropdown-menu-content-available-height))] w-[280px] max-w-[calc(100vw-24px)] flex-col gap-0 rounded-2xl bg-bg-page p-3"
      >
        <SkillMenuPanel onUpload={onUpload} />
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
