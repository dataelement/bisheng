import { useState, type ReactNode } from 'react';
import { Button, Switch, Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { ActionMenuContent, ActionMenuDivider, ActionMenuItem } from '~/components/ActionMenu';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '~/components/ui/Dialog';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { useLocalize } from '~/hooks';
import { DemoTag } from '~/mock/demo/DemoTag';
import { isDemoId } from '~/mock/demo/ids';
import { SkillError, type CenterSkill, type PersonalSkill } from './types';
import { useSkillCenter } from './useSkillCenter';

interface SkillDetailsProps {
  skill: CenterSkill;
  /** The on / off switch is being saved. */
  toggling?: boolean;
  onClose: () => void;
  onToggle: (skill: PersonalSkill, enabled: boolean) => void;
  onUpdate: (skill: PersonalSkill) => void;
}

const ICON_BUTTON = 'flex size-8 shrink-0 items-center justify-center rounded-md text-text-2 outline-none transition-colors hover:bg-fill-2 focus-visible:bg-fill-2 data-[state=open]:bg-fill-2';

function MetaItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-caption text-text-3">{label}</dt>
      <dd className="mt-1 break-all text-body-sm text-text-1">{children}</dd>
    </div>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-caption text-text-3">{children}</h3>;
}

/** Hand the uploaded file back to the user under its original name. */
function downloadSkillFile(skill: PersonalSkill) {
  const url = URL.createObjectURL(skill.file);
  const link = document.createElement('a');
  link.href = url;
  link.download = skill.fileName;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * One skill, in a dialog: the header carries the name, the on / off switch and the 更多
 * menu (update / download / delete); the body reads top to bottom — where it came from,
 * what it is for, then the SKILL.md instructions themselves and the files that ship with it.
 */
export function SkillDetails({ skill, toggling = false, onClose, onToggle, onUpdate }: SkillDetailsProps) {
  const localize = useLocalize();
  const { mutation } = useSkillCenter();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');
  const personal = skill.source === 'personal' ? skill : null;
  // DEV sample rows (~/mock/demo) are not in the store: they can be read, switched for
  // the session and downloaded, but not replaced or deleted.
  const demoKey = personal ? skill.id : skill.name;
  const stored = personal !== null && !isDemoId(demoKey);
  const switchLabel = localize('com_skill_center_enabled_setting');

  const handleDelete = async () => {
    if (!personal || !stored || mutation.isLoading) return;
    setError('');
    try {
      await mutation.mutateAsync({ kind: 'delete', target: personal });
      onClose();
    } catch (cause) {
      setError(cause instanceof SkillError ? cause.code : 'storage');
    }
  };

  return <>
    <Dialog open onOpenChange={(next) => { if (!next && !mutation.isLoading && !confirmDelete) onClose(); }}>
      <DialogContent
        close={false}
        className="flex max-h-[85dvh] w-[calc(100%-40px)] max-w-[720px] flex-col gap-0 overflow-hidden rounded-2xl border-border-base bg-bg-page p-0 sm:rounded-2xl max-[575px]:h-dvh max-[575px]:max-h-dvh max-[575px]:w-full max-[575px]:rounded-none"
      >
        <header className="flex shrink-0 items-center gap-3 border-b-[0.5px] border-border-base py-4 pl-6 pr-4">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border-[0.5px] border-border-base text-text-2">
            <Outlined.Skill className="size-[18px]" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-1.5">
              <DialogTitle className="min-w-0 truncate text-h4 font-medium leading-6 text-text-1">{skill.displayName}</DialogTitle>
              <DemoTag id={demoKey} className="shrink-0" />
            </div>
            <p className="mt-0.5 truncate text-caption text-text-3">{skill.name}</p>
          </div>
          {personal ? (
            <Switch
              className="shrink-0"
              checked={personal.enabled}
              loading={toggling}
              aria-label={switchLabel}
              onCheckedChange={(enabled) => onToggle(personal, enabled)}
            />
          ) : (
            <Tooltip content={localize('com_skill_center_platform_always_on')}>
              <span className="flex shrink-0 items-center"><Switch checked disabled aria-label={switchLabel} /></span>
            </Tooltip>
          )}
          {personal && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" aria-label={localize('com_skill_center_more')} className={ICON_BUTTON}>
                  <Outlined.More className="size-4 rotate-90" />
                </button>
              </DropdownMenuTrigger>
              <ActionMenuContent>
                {stored && <ActionMenuItem icon={<Outlined.Upload />} label={localize('com_skill_center_update')} onSelect={() => onUpdate(personal)} />}
                <ActionMenuItem icon={<Outlined.Download />} label={localize('com_ui_download')} onSelect={() => downloadSkillFile(personal)} />
                {stored && <>
                  <ActionMenuDivider />
                  <ActionMenuItem danger icon={<Outlined.Delete />} label={localize('com_skill_center_delete')} onSelect={() => setConfirmDelete(true)} />
                </>}
              </ActionMenuContent>
            </DropdownMenu>
          )}
          <button type="button" aria-label={localize('com_skill_center_close')} disabled={mutation.isLoading} onClick={onClose} className={ICON_BUTTON}>
            <Outlined.Close className="size-4" />
          </button>
        </header>

        <div className="scroll-on-scroll flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-6">
          <dl className="grid grid-cols-3 gap-4 max-[575px]:grid-cols-1">
            <MetaItem label={localize('com_skill_center_source')}>
              {localize(personal ? 'com_skill_center_source_personal' : 'com_skill_center_source_platform')}
            </MetaItem>
            {personal && <>
              <MetaItem label={localize('com_skill_center_updated')}>{new Date(personal.updatedAt).toLocaleString()}</MetaItem>
              <MetaItem label={localize('com_skill_center_file')}>{personal.fileName}</MetaItem>
            </>}
          </dl>

          <section className="flex flex-col gap-2">
            <SectionTitle>{localize('com_skill_center_description')}</SectionTitle>
            <DialogDescription className="whitespace-pre-wrap break-words text-body text-text-1">{skill.description}</DialogDescription>
          </section>

          {personal ? <>
            <section className="flex flex-col gap-2">
              <SectionTitle>SKILL.md</SectionTitle>
              <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border-[0.5px] border-border-base bg-fill-1 p-4 font-sans text-body-sm text-text-2">{personal.instructions}</pre>
            </section>
            {personal.files.length > 0 && (
              <details className="text-body-sm text-text-2">
                <summary className="cursor-pointer text-caption text-text-3">{localize('com_skill_center_files', { count: personal.files.length })}</summary>
                <ul className="mt-2 max-h-48 overflow-y-auto text-caption text-text-3">{personal.files.map((file) => <li key={file} className="break-all py-1">{file}</li>)}</ul>
              </details>
            )}
            <p className="text-caption text-text-3">{localize('com_skill_center_preview_notice')}</p>
          </> : <p className="rounded-xl bg-fill-1 p-4 text-body-sm text-text-3">{localize('com_skill_center_platform_note')}</p>}
        </div>
      </DialogContent>
    </Dialog>
    <Dialog open={confirmDelete} onOpenChange={(next) => { if (!mutation.isLoading) setConfirmDelete(next); }}>
      <DialogContent close={false}>
        <DialogTitle>{localize('com_skill_center_delete_title')}</DialogTitle>
        <DialogDescription>{localize('com_skill_center_delete_confirm', { name: skill.displayName })}</DialogDescription>
        {error && <p role="alert" className="text-body-sm text-danger">{localize(`com_skill_center_error_${error}`)}</p>}
        <div className="flex justify-end gap-2">
          <Button color="default" variant="outlined" disabled={mutation.isLoading} onClick={() => setConfirmDelete(false)}>{localize('com_skill_center_cancel')}</Button>
          <Button color="danger" loading={mutation.isLoading} onClick={() => void handleDelete()}>{localize('com_skill_center_delete')}</Button>
        </div>
      </DialogContent>
    </Dialog>
  </>;
}
