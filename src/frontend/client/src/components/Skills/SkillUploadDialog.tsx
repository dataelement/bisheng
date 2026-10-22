import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState, type DragEvent } from 'react';
import { Outlined } from 'bisheng-icons';
import { Button } from '@bisheng/ui';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import {
  checkPersonalSkill,
  createPersonalSkill,
  findPersonalSkillByImport,
  getPersonalSkillUsage,
  overwritePersonalSkill,
} from '~/api/skillCenter';
import { translateApiErrorMessage } from '~/api/request';
import { useSkillCenter } from './useSkillCenter';
import { SkillRequestError, type SkillRecord } from './types';

interface SkillUploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target?: SkillRecord;
  onSaved?: () => void;
}

const MIB = 1024 * 1024;
const MAX_UPLOAD_BYTES = 50 * MIB;
const QUOTA_ERROR_CODES = new Set([11061, 11062]);

export function SkillUploadDialog({ open, onOpenChange, target, onSaved }: SkillUploadDialogProps) {
  const localize = useLocalize();
  const { refresh } = useSkillCenter();
  const usage = useQuery(['skill-center', 'usage'], getPersonalSkillUsage, { enabled: open, retry: false });
  const [file, setFile] = useState<File>();
  const [dragging, setDragging] = useState(false);
  const [checking, setChecking] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [errorCode, setErrorCode] = useState<number>();
  const [duplicate, setDuplicate] = useState<{ skillId: number; contentHash: string }>();
  const [saving, setSaving] = useState(false);
  const checkSeq = useRef(0);
  const importId = useRef(globalThis.crypto?.randomUUID?.() ?? `import-${Date.now()}`);
  const input = useRef<HTMLInputElement>(null);
  const atCountLimit = !target && (usage.data?.count ?? 0) >= (usage.data?.countLimit ?? 20);
  const atByteLimit = !target && (usage.data?.usedBytes ?? 0) >= (usage.data?.bytesLimit ?? 209715200);
  const quotaBlocked = atCountLimit || atByteLimit;
  const showFileError = Boolean(error) && !(quotaBlocked && errorCode != null && QUOTA_ERROR_CODES.has(errorCode));

  useEffect(() => () => {
    checkSeq.current += 1;
  }, []);

  const choose = (files: FileList | null) => {
    setError('');
    setErrorCode(undefined);
    setDuplicate(undefined);
    setReady(false);
    const selected = files?.length === 1 ? files[0] : undefined;
    setFile(selected);
    if (files && files.length > 1) {
      setError(localize('com_skill_center_error_multiple'));
      setChecking(false);
      return;
    }
    if (selected && !/\.(md|zip|skill)$/i.test(selected.name)) {
      setChecking(false);
      setError(localize('com_skill_center_error_format'));
      return;
    }
    if (selected && (!selected.size || selected.size > MAX_UPLOAD_BYTES)) {
      setChecking(false);
      setError(localize('com_skill_center_error_size'));
      return;
    }
    if (!selected) return;
    if (quotaBlocked) {
      setChecking(false);
      return;
    }
    void inspect(selected);
  };

  const inspect = async (selected: File) => {
    const seq = checkSeq.current + 1;
    checkSeq.current = seq;
    setChecking(true);
    try {
      await checkPersonalSkill(selected, target?.id);
      if (checkSeq.current !== seq) return;
      setReady(true);
    } catch (cause) {
      if (checkSeq.current !== seq) return;
      const sameName = cause instanceof SkillRequestError
        && cause.statusCode === 11055
        && Number.isInteger(Number(cause.data?.skill_id))
        && Boolean(cause.data?.content_hash || target?.contentHash);
      if (sameName) setReady(true);
      fail(cause);
    } finally {
      if (checkSeq.current === seq) setChecking(false);
    }
  };
  const allowDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (!saving) setDragging(true);
  };
  const endDrag = (event: DragEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDragging(false);
  };
  const dropFile = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
    if (saving) return;
    choose(event.dataTransfer.files);
  };
  const close = () => {
    if (saving) return;
    onOpenChange(false);
  };
  const fail = (cause: unknown) => {
    if (cause instanceof SkillRequestError && cause.statusCode === 11055) {
      const skillId = Number(cause.data?.skill_id);
      const contentHash = String(cause.data?.content_hash ?? target?.contentHash ?? '');
      if (Number.isInteger(skillId) && contentHash) {
        setDuplicate({ skillId, contentHash });
        setError('');
        setErrorCode(undefined);
        return;
      }
    }
    if (cause instanceof SkillRequestError) {
      setErrorCode(cause.statusCode);
      setError(translateApiErrorMessage({
        status_code: cause.statusCode,
        status_message: cause.statusMessage,
        data: cause.data,
      }));
      return;
    }
    setErrorCode(undefined);
    setError(localize('com_skill_center_error_storage'));
  };
  const save = async () => {
    if (!file || !ready || saving || atCountLimit || atByteLimit) return;
    setSaving(true);
    setError('');
    try {
      const existing = await findPersonalSkillByImport(importId.current);
      if (!existing) {
        if (target || duplicate) {
          const skillId = target?.id ?? duplicate?.skillId;
          const expected = target?.contentHash ?? duplicate?.contentHash;
          if (skillId == null || !expected) return;
          await overwritePersonalSkill(skillId, file, importId.current, expected);
        } else {
          await createPersonalSkill(file, importId.current);
        }
      }
      await refresh();
      onSaved?.();
      onOpenChange(false);
    } catch (cause) {
      fail(cause);
    } finally {
      setSaving(false);
    }
  };

  const used = ((usage.data?.usedBytes ?? 0) / MIB).toFixed(1);
  const limit = ((usage.data?.bytesLimit ?? 209715200) / MIB).toFixed(0);

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) close(); }}>
      <DialogContent close={false} className="max-h-[90dvh] max-w-[560px] gap-5 overflow-y-auto rounded-xl border-border-base bg-bg-page max-[575px]:h-dvh max-[575px]:max-h-dvh max-[575px]:rounded-none">
        <DialogTitle>{localize(target ? 'com_skill_center_update' : 'com_skill_center_upload')}</DialogTitle>
        <DialogDescription className="text-body-sm text-text-3">
          {localize('com_skill_center_usage', {
            count: usage.data?.count ?? 0,
            countLimit: usage.data?.countLimit ?? 20,
            used,
            bytesLimit: limit,
          })}
        </DialogDescription>
        <p className="text-body-sm text-text-3">{localize('com_skill_center_formats')}</p>
        <input ref={input} type="file" accept=".md,.zip,.skill" className="hidden" onChange={(event) => { choose(event.target.files); event.target.value = ''; }} />
        <div
          className={cn(
            'flex flex-col items-center gap-3 rounded-xl border border-dashed bg-fill-1 p-7 text-center',
            dragging ? 'border-blue-500 bg-blue-500/10' : 'border-border-base',
          )}
          onDragEnter={allowDrop}
          onDragOver={allowDrop}
          onDragLeave={endDrag}
          onDrop={dropFile}
        >
          <Outlined.Skill className="size-8 text-text-3" aria-hidden />
          <p className="text-body text-text-1">{file ? file.name : localize('com_skill_center_drop')}</p>
          {checking && <p role="status" className="text-body-sm text-text-3">{localize('com_skill_center_parsing')}</p>}
          <Button color="default" variant="outlined" disabled={saving} onClick={() => input.current?.click()}>
            {localize(file || showFileError ? 'com_skill_center_reselect' : 'com_skill_center_choose')}
          </Button>
        </div>
        {showFileError && (
          <div role="alert" className="space-y-2">
            <p className="text-body-sm text-red-600">{error}</p>
            <Button color="default" variant="outlined" onClick={() => input.current?.click()}>{localize('com_skill_center_reselect')}</Button>
          </div>
        )}
        {duplicate && !target && (
          <div className="space-y-3 rounded-xl border border-border-base p-4">
            <p className="text-body-sm text-text-1">{localize('com_skill_center_replace_confirm')}</p>
            <div className="flex justify-end gap-2">
              <Button color="default" variant="outlined" disabled={saving} onClick={() => setDuplicate(undefined)}>{localize('com_skill_center_cancel')}</Button>
              <Button loading={saving} onClick={() => void save()}>{localize('com_skill_center_replace')}</Button>
            </div>
          </div>
        )}
        {(atCountLimit || atByteLimit) && <p role="alert" className="text-body-sm text-red-600">{localize('com_skill_center_quota_full')}</p>}
        <div className="flex justify-end gap-2">
          <Button color="default" variant="outlined" disabled={saving} onClick={close}>{localize('com_skill_center_cancel')}</Button>
          {!duplicate && (
            <Button
              loading={saving}
              disabled={!file || checking || !ready || atCountLimit || atByteLimit}
              onClick={() => void save()}
            >
              {localize(target ? 'com_skill_center_save_update' : 'com_skill_center_add')}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
