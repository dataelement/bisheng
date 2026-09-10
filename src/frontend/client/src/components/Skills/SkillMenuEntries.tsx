import { lazy, Suspense, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { skillCenterPath, skillCenterPreviewEnabled } from './types';

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

export function SkillMenuEntries({ onUpload }: { onUpload: () => void }) {
  const localize = useLocalize();
  const navigate = useNavigate();
  if (!skillCenterPreviewEnabled) return null;
  return <>
    <div className="my-1 h-px bg-border-base" />
    <DropdownMenuItem onSelect={onUpload} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-body-sm text-text-1">
      <Outlined.Plus className="size-4 text-text-2" />{localize('com_skill_center_upload')}
    </DropdownMenuItem>
    <DropdownMenuItem onSelect={() => navigate(skillCenterPath)} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-2 text-body-sm text-text-1">
      <Outlined.Newspaper className="size-4 text-text-2" />{localize('com_skill_center_title')}
    </DropdownMenuItem>
  </>;
}
