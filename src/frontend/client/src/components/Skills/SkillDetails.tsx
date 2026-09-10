import { useState } from 'react';
import { Button, Switch, Tag } from '@bisheng/ui';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '~/components/ui/Dialog';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '~/components/ui/Sheet';
import { useLocalize } from '~/hooks';
import { SkillError, type CenterSkill, type PersonalSkill } from './types';
import { useSkillCenter } from './useSkillCenter';

interface SkillDetailsProps {
  skill: CenterSkill;
  onClose: () => void;
  onUpdate: (skill: PersonalSkill) => void;
}

export function SkillDetails({ skill, onClose, onUpdate }: SkillDetailsProps) {
  const localize = useLocalize();
  const { mutation } = useSkillCenter();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');
  const change = async (action: 'toggle' | 'delete', enabled = false) => {
    if (skill.source !== 'personal' || mutation.isLoading) return;
    setError('');
    try {
      await mutation.mutateAsync(action === 'delete' ? { kind: 'delete', target: skill } : { kind: 'toggle', target: skill, enabled });
      if (action === 'delete') onClose();
    } catch (cause) { setError(cause instanceof SkillError ? cause.code : 'storage'); }
  };
  return <>
    <Sheet open onOpenChange={(next) => { if (!next && !mutation.isLoading && !confirmDelete) onClose(); }}>
      <SheetContent hideClose className="w-full gap-0 bg-bg-page sm:max-w-[480px]">
        <div className="flex items-center justify-between border-b border-border-base p-5">
          <p className="text-body text-text-2">{localize('com_skill_center_details')}</p>
          <Button color="default" variant="text" disabled={mutation.isLoading} onClick={onClose}>{localize('com_skill_center_close')}</Button>
        </div>
        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6">
          <div className="space-y-3">
            <Tag color="skill">Skill</Tag>
            <SheetTitle className="break-words text-h3 text-text-1">{skill.displayName}</SheetTitle>
            <SheetDescription className="whitespace-pre-wrap break-words text-body text-text-3">{skill.description}</SheetDescription>
          </div>
          <dl className="grid grid-cols-[80px_1fr] gap-x-4 gap-y-3 text-body-sm">
            <dt className="text-text-3">{localize('com_skill_center_identifier')}</dt><dd className="break-all text-text-1">{skill.name}</dd>
            <dt className="text-text-3">{localize('com_skill_center_source')}</dt><dd className="text-text-1">{localize(skill.source === 'personal' ? 'com_skill_center_source_personal' : 'com_skill_center_source_platform')}</dd>
            {skill.source === 'personal' && <>
              <dt className="text-text-3">{localize('com_skill_center_updated')}</dt><dd className="text-text-1">{new Date(skill.updatedAt).toLocaleString()}</dd>
              <dt className="text-text-3">{localize('com_skill_center_file')}</dt><dd className="break-all text-text-1">{skill.fileName}</dd>
            </>}
          </dl>
          {skill.source === 'personal' ? <>
            <div className="rounded-xl bg-fill-1 p-4">
              <div className="flex items-center justify-between gap-4">
                <span className="text-body text-text-1">{localize('com_skill_center_enabled_setting')}</span>
                <Switch checked={skill.enabled} loading={mutation.isLoading} aria-label={localize('com_skill_center_enabled_setting')} onCheckedChange={(enabled) => void change('toggle', enabled)} />
              </div>
              <p className="mt-3 text-caption text-text-3">{localize('com_skill_center_preview_notice')}</p>
            </div>
            <details className="rounded-xl border border-border-base p-4 text-body-sm text-text-2">
              <summary className="cursor-pointer">{localize('com_skill_center_instructions')}</summary>
              <pre className="mt-4 max-h-72 overflow-y-auto whitespace-pre-wrap break-words font-sans text-body-sm text-text-3">{skill.instructions}</pre>
            </details>
            <details className="text-body-sm text-text-2">
              <summary className="cursor-pointer">{localize('com_skill_center_files', { count: skill.files.length })}</summary>
              <ul className="mt-3 max-h-48 overflow-y-auto text-caption text-text-3">{skill.files.map((file) => <li key={file} className="break-all py-1">{file}</li>)}</ul>
            </details>
          </> : <p className="rounded-xl bg-fill-1 p-4 text-body-sm text-text-3">{localize('com_skill_center_platform_note')}</p>}
          {error && <p role="alert" className="text-body-sm text-red-600">{localize(`com_skill_center_error_${error}`)}</p>}
        </div>
        {skill.source === 'personal' && <div className="flex justify-between gap-3 border-t border-border-base p-5">
          <Button color="danger" variant="text" disabled={mutation.isLoading} onClick={() => setConfirmDelete(true)}>{localize('com_skill_center_delete')}</Button>
          <Button color="default" variant="outlined" disabled={mutation.isLoading} onClick={() => onUpdate(skill)}>{localize('com_skill_center_update')}</Button>
        </div>}
      </SheetContent>
    </Sheet>
    <Dialog open={confirmDelete} onOpenChange={(next) => { if (!mutation.isLoading) setConfirmDelete(next); }}>
      <DialogContent close={false}>
        <DialogTitle>{localize('com_skill_center_delete_title')}</DialogTitle>
        <DialogDescription>{localize('com_skill_center_delete_confirm', { name: skill.displayName })}</DialogDescription>
        {error && <p role="alert" className="text-body-sm text-red-600">{localize(`com_skill_center_error_${error}`)}</p>}
        <div className="flex justify-end gap-2">
          <Button color="default" variant="outlined" disabled={mutation.isLoading} onClick={() => setConfirmDelete(false)}>{localize('com_skill_center_cancel')}</Button>
          <Button color="danger" loading={mutation.isLoading} onClick={() => void change('delete')}>{localize('com_skill_center_delete')}</Button>
        </div>
      </DialogContent>
    </Dialog>
  </>;
}
