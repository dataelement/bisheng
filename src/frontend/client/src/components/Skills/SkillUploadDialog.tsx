import { useRef, useState } from 'react';
import { Outlined } from 'bisheng-icons';
import { Button, Tag } from '@bisheng/ui';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';
import { parseSkillFile } from './parseSkill';
import { useSkillCenter } from './useSkillCenter';
import { SkillError, type PersonalSkill, type SkillManifest } from './types';

interface SkillUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target?: PersonalSkill;
  onSaved?: () => void;
}

export function SkillUploadDialog({ open, onOpenChange, target, onSaved }: SkillUploadDialogProps) {
  const localize = useLocalize();
  const { scope, identity, personal, platform, mutation } = useSkillCenter();
  const [candidate, setCandidate] = useState<{ file: File; manifest: SkillManifest }>();
  const [error, setError] = useState('');
  const [parsing, setParsing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const generation = useRef(0);
  const input = useRef<HTMLInputElement>(null);

  const choose = async (files: FileList | null) => {
    const version = ++generation.current;
    setParsing(false);
    setCandidate(undefined);
    setError('');
    if (!files?.length) return;
    if (files.length !== 1) { setError('multiple'); return; }
    const file = files[0];
    setParsing(true);
    try {
      const manifest = await parseSkillFile(file);
      if (version === generation.current) setCandidate({ file, manifest });
    } catch (cause) {
      if (version === generation.current) setError(cause instanceof SkillError ? cause.code : 'archive');
    } finally {
      if (version === generation.current) setParsing(false);
    }
  };

  const close = () => {
    if (mutation.isLoading) return;
    generation.current += 1;
    onOpenChange(false);
  };
  const duplicate = candidate && personal.data?.some((skill) => skill.name === candidate.manifest.name && skill.id !== target?.id);
  const sharedName = candidate && platform.data?.some((skill) => skill.name === candidate.manifest.name);
  const save = async () => {
    if (!candidate || duplicate || mutation.isLoading) return;
    setError('');
    try {
      await mutation.mutateAsync({ kind: 'save', ...candidate, target });
      onSaved?.();
      onOpenChange(false);
    } catch (cause) {
      setError(cause instanceof SkillError ? cause.code : 'storage');
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) close(); }}>
      <DialogContent close={false} className="max-h-[90dvh] max-w-[560px] gap-5 overflow-y-auto rounded-xl border-border-base bg-bg-page max-[575px]:h-dvh max-[575px]:max-h-dvh max-[575px]:rounded-none">
        <div className="flex items-center justify-between gap-3">
          <DialogTitle>{localize(target ? 'com_skill_center_update' : 'com_skill_center_upload')}</DialogTitle>
          <Tag color="warning">{localize('com_skill_center_preview')}</Tag>
        </div>
        <DialogDescription className="text-body-sm text-text-3">
          {localize('com_skill_center_preview_notice')}
        </DialogDescription>
        {target && <p className="text-body-sm text-text-2">{localize('com_skill_center_replacing', { name: target.displayName })}</p>}
        <input ref={input} type="file" accept=".md,.zip,.skill" className="hidden" onChange={(event) => { void choose(event.target.files); event.target.value = ''; }} />
        <div
          onDragOver={(event) => { event.preventDefault(); if (!mutation.isLoading) setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => { event.preventDefault(); setDragging(false); if (!mutation.isLoading) void choose(event.dataTransfer.files); }}
          className={`flex flex-col items-center gap-3 rounded-xl border border-dashed p-7 text-center ${dragging ? 'border-blue-500 bg-blue-50' : 'border-border-base bg-fill-1'}`}
        >
          <Outlined.Newspaper className="size-8 text-text-3" aria-hidden />
          <p className="text-body text-text-1">{localize('com_skill_center_drop')}</p>
          <p className="text-caption text-text-3">{localize('com_skill_center_formats')}</p>
          <Button color="default" variant="outlined" loading={parsing} disabled={mutation.isLoading} onClick={() => input.current?.click()}>
            {localize(candidate ? 'com_skill_center_reselect' : 'com_skill_center_choose')}
          </Button>
        </div>
        {parsing && <p role="status" className="text-body-sm text-text-3">{localize('com_skill_center_parsing')}</p>}
        {candidate && (
          <section className="space-y-3 rounded-xl border border-border-base p-4">
            <div className="flex items-start gap-3">
              <Outlined.Newspaper className="mt-0.5 size-5 shrink-0 text-text-2" />
              <div className="min-w-0">
                <p className="break-words text-h4 text-text-1">{candidate.manifest.displayName}</p>
                <p className="mt-1 break-words text-body-sm text-text-3">{candidate.manifest.description}</p>
              </div>
            </div>
            <p className="break-all text-caption text-text-3">{candidate.file.name} · {(candidate.file.size / (1024 * 1024)).toFixed(2)} MiB</p>
            <details className="text-caption text-text-3">
              <summary className="cursor-pointer py-1">{localize('com_skill_center_files', { count: candidate.manifest.files.length })}</summary>
              <ul className="mt-2 max-h-28 overflow-y-auto font-mono">{candidate.manifest.files.map((file) => <li key={file} className="break-all py-0.5">{file}</li>)}</ul>
            </details>
            <p className="text-caption text-text-3">{localize(target ? 'com_skill_center_update_note' : 'com_skill_center_add_note')}</p>
          </section>
        )}
        {sharedName && <p className="text-body-sm text-text-3">{localize('com_skill_center_shared_name')}</p>}
        {(error || duplicate || identity.isError || personal.isError) && (
          <p role="alert" className="text-body-sm text-red-600">{localize(`com_skill_center_error_${error || (duplicate ? 'duplicate' : identity.isError ? 'identity' : 'storage')}`)}</p>
        )}
        <div className="flex justify-end gap-2 max-[575px]:mt-auto max-[575px]:[&>*]:flex-1">
          <Button color="default" variant="outlined" disabled={mutation.isLoading} onClick={close}>{localize('com_skill_center_cancel')}</Button>
          <Button loading={mutation.isLoading} disabled={!candidate || parsing || !!duplicate || !scope || identity.isError || !personal.isSuccess} onClick={() => void save()}>
            {localize(target ? 'com_skill_center_save_update' : 'com_skill_center_add')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
