import { useQuery } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';
import { Button, Switch } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '~/components/ui/Dialog';
import { getSkillDetail, getSkillFile } from '~/api/skillCenter';
import { useLocalize } from '~/hooks';
import { DemoTag } from '~/mock/demo/DemoTag';
import { isDemoId } from '~/mock/demo/ids';
import { cn } from '~/utils';
import type { SkillRecord } from './types';
import { useSkillCenter } from './useSkillCenter';

interface SkillDetailsProps {
  skill: SkillRecord;
  /** The on / off switch is being saved. */
  toggling?: boolean;
  onClose: () => void;
  onToggle: (skill: SkillRecord, enabled: boolean) => void;
  onUpdate: (skill: SkillRecord) => void;
}

const SKILL_MD = 'SKILL.md';
const ICON_BUTTON = 'flex size-8 shrink-0 items-center justify-center rounded-md text-text-2 outline-none transition-colors hover:bg-fill-2 focus-visible:bg-fill-2';

/** Quiet markdown, matching the workbench skill drawer rather than chat prose. */
const MD_COMPONENTS: Components = {
  h1: ({ children }) => <h1 className="mb-3 mt-0 break-words text-h4 font-medium text-text-1">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-4 break-words text-body font-medium text-text-1">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1.5 mt-3 break-words text-body-sm font-medium text-text-1">{children}</h3>,
  p: ({ children }) => <p className="mb-3 break-words text-body-sm leading-7 text-text-2">{children}</p>,
  ul: ({ children }) => <ul className="my-2.5 list-disc space-y-1.5 pl-5 text-body-sm leading-7 text-text-2">{children}</ul>,
  ol: ({ children }) => <ol className="my-2.5 list-decimal space-y-1.5 pl-5 text-body-sm leading-7 text-text-2">{children}</ol>,
  li: ({ children }) => <li className="break-words pl-1 leading-7">{children}</li>,
  a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer" className="break-words text-blue-500 underline underline-offset-2">{children}</a>,
  strong: ({ children }) => <strong className="font-medium text-text-1">{children}</strong>,
  code: ({ children }) => <code className="rounded bg-fill-2 px-1.5 py-0.5 font-mono text-caption text-text-1">{children}</code>,
  pre: ({ children }) => <pre className="my-3 overflow-x-auto rounded-[10px] bg-text-1 p-3.5 font-mono text-caption leading-relaxed text-white [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit">{children}</pre>,
  blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-border-base pl-3 text-text-3">{children}</blockquote>,
  hr: () => <hr className="my-4 border-border-base" />,
  table: ({ children }) => <table className="my-3 border-collapse text-caption">{children}</table>,
  th: ({ children }) => <th className="border border-border-base bg-fill-2 px-2.5 py-1.5 text-left font-medium">{children}</th>,
  td: ({ children }) => <td className="border border-border-base px-2.5 py-1.5">{children}</td>,
};

function preferredFile(files: string[] | undefined): string {
  const list = files ?? [];
  if (list.includes(SKILL_MD)) return SKILL_MD;
  return list[0] ?? SKILL_MD;
}

/**
 * Left file tree and right reader, the same split as the workbench skill drawer.
 * SKILL.md toggles between rendered preview and raw source; other files are read-only.
 */
function SkillReader({ skill }: { skill: SkillRecord }) {
  const localize = useLocalize();
  const [selectedPath, setSelectedPath] = useState(() => preferredFile(skill.files));
  const [mode, setMode] = useState<'preview' | 'source'>('preview');
  useEffect(() => {
    setSelectedPath(preferredFile(skill.files));
    setMode('preview');
  }, [skill.id, skill.files]);

  const isSkillMd = selectedPath === SKILL_MD;
  const sourceText = skill.sourceText ?? '';
  const needsFile = selectedPath !== '' && !(isSkillMd && (mode === 'preview' || sourceText !== ''));
  const file = useQuery(
    ['skill-center', 'file', skill.id, selectedPath],
    () => getSkillFile(skill.id, selectedPath),
    { enabled: needsFile, retry: false },
  );
  const raw = isSkillMd ? (sourceText || file.data || '') : (file.data ?? '');
  const body: ReactNode = file.isError && needsFile
    ? <p className="text-body-sm text-text-3">{localize('com_skill_center_file_failed')}</p>
    : file.isLoading && needsFile
      ? <p className="text-body-sm text-text-3">{localize('com_skill_center_file_loading')}</p>
      : isSkillMd && mode === 'preview'
        ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{skill.preview || raw}</ReactMarkdown>
        : <pre className="whitespace-pre-wrap break-words font-mono text-caption leading-7 text-text-2">{raw || localize('com_skill_center_file_empty')}</pre>;

  return (
    <div className="mt-[18px] flex min-h-0 flex-1 gap-4 max-[575px]:flex-col">
      <div className="w-[220px] shrink-0 overflow-y-auto rounded-[11px] border border-border-base bg-fill-1 max-[575px]:max-h-40 max-[575px]:w-full">
        <p className="px-3.5 pb-2 pt-3 text-caption tracking-wider text-text-4">{localize('com_skill_center_detail_files')}</p>
        {(skill.files ?? []).map((filePath) => {
          const selected = selectedPath === filePath;
          return (
            <button
              key={filePath}
              type="button"
              aria-pressed={selected}
              title={filePath}
              onClick={() => setSelectedPath(filePath)}
              className={cn(
                'flex w-full items-center gap-2 border-l-2 px-3.5 py-2 text-left font-mono text-caption outline-none transition-colors',
                selected
                  ? 'border-blue-500 bg-blue-500/10 text-blue-500'
                  : 'border-transparent text-text-2 hover:bg-fill-2',
              )}
            >
              <Outlined.File className={cn('size-3.5 shrink-0', selected ? 'text-blue-500' : 'text-text-4')} />
              <span className="min-w-0 truncate">{filePath}</span>
            </button>
          );
        })}
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="mb-2.5 flex items-center justify-between gap-3">
          <span className="min-w-0 truncate font-mono text-caption text-text-4" title={selectedPath}>{selectedPath}</span>
          {isSkillMd ? (
            <div className="inline-flex shrink-0 overflow-hidden rounded-lg border border-border-base">
              {(['preview', 'source'] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setMode(item)}
                  className={cn(
                    'px-3.5 py-1.5 text-caption font-medium transition-colors',
                    mode === item ? 'btn-brand-primary bg-blue-500 text-white' : 'bg-white text-text-3 hover:bg-fill-1',
                  )}
                >
                  {localize(item === 'preview' ? 'com_skill_center_detail_preview' : 'com_skill_center_detail_source')}
                </button>
              ))}
            </div>
          ) : (
            <span className="inline-flex shrink-0 items-center gap-1.5 text-caption text-text-4">
              <Outlined.Info className="size-3.5" />{localize('com_skill_center_detail_readonly')}
            </span>
          )}
        </div>
        <div className={cn(
          'min-h-0 flex-1 overflow-auto rounded-[11px] border border-border-base px-6 py-5',
          isSkillMd && mode === 'preview' ? 'bg-white' : 'bg-fill-1',
        )}
        >
          {body}
        </div>
      </div>
    </div>
  );
}

/**
 * One skill, in a dialog laid out like the workbench skill drawer: title and
 * actions, then the id and status, then the file tree beside the file body.
 */
export function SkillDetails({ skill, toggling = false, onClose, onToggle, onUpdate }: SkillDetailsProps) {
  const localize = useLocalize();
  const { mutation } = useSkillCenter();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState('');
  const detail = useQuery(['skill-center', 'detail', skill.id], () => getSkillDetail(skill.id), { retry: false });
  // The list row owns source (personal vs enterprise). Detail only fills the file body.
  const shown: SkillRecord = detail.data
    ? {
      ...skill,
      preview: detail.data.preview,
      sourceText: detail.data.sourceText,
      files: detail.data.files,
      bundleMissing: detail.data.bundleMissing,
      contentHash: detail.data.contentHash,
    }
    : skill;
  const files = shown.files ?? [];
  const personal = shown.source === 'personal' ? shown : null;
  // DEV sample rows (~/mock/demo) are not in the store: they can be read and switched
  // for the session, but not replaced or deleted.
  const demoKey = personal ? String(skill.id) : skill.name;
  const stored = personal !== null && !isDemoId(demoKey);
  const switchLabel = localize('com_skill_center_enabled_setting');

  const handleDelete = async () => {
    if (!personal || !stored || mutation.isLoading) return;
    setError('');
    try {
      await mutation.mutateAsync({ kind: 'delete', target: personal });
      onClose();
    } catch {
      setError('delete');
    }
  };

  return <>
    <Dialog open onOpenChange={(next) => { if (!next && !mutation.isLoading && !confirmDelete) onClose(); }}>
      <DialogContent
        close={false}
        className="flex h-[min(760px,85dvh)] w-[calc(100%-40px)] max-w-[860px] flex-col gap-0 overflow-hidden rounded-2xl border-border-base bg-white p-0 sm:rounded-2xl max-[575px]:h-dvh max-[575px]:max-h-dvh max-[575px]:w-full max-[575px]:rounded-none"
      >
        <div className="flex min-h-0 flex-1 flex-col px-7 pb-6 pt-6 max-[575px]:px-4">
          <div className="flex items-start gap-3">
            <div className="flex min-w-0 flex-1 items-center gap-1.5">
              <DialogTitle className="min-w-0 truncate text-[19px] font-medium leading-tight text-text-1" title={shown.displayName}>
                {shown.displayName}
              </DialogTitle>
              <DemoTag id={demoKey} className="shrink-0" />
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {stored && !shown.bundleMissing && (
                <Button color="default" variant="text" size="medium" onClick={() => onUpdate(personal)}>
                  <Outlined.Edit />{localize('com_skill_center_update')}
                </Button>
              )}
              {stored && (
                <Button color="danger" variant="text" size="medium" onClick={() => setConfirmDelete(true)}>
                  <Outlined.Delete />{localize('com_skill_center_delete')}
                </Button>
              )}
              <button type="button" aria-label={localize('com_skill_center_close')} disabled={mutation.isLoading} onClick={onClose} className={ICON_BUTTON}>
                <Outlined.Close className="size-4" />
              </button>
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2.5">
            <span className="max-w-full truncate rounded-md border border-border-base px-[7px] py-[3px] font-mono text-caption font-medium text-text-3" title={shown.name}>
              {localize('com_skill_center_detail_id', { name: shown.name })}
            </span>
            <span className={cn(
              'shrink-0 whitespace-nowrap rounded-full px-[11px] py-1 text-caption font-medium',
              shown.enabled ? 'bg-blue-500/10 text-blue-500' : 'bg-fill-2 text-text-3',
            )}
            >
              {localize(shown.enabled ? 'com_skill_center_status_enabled' : 'com_skill_center_disabled_tag')}
            </span>
            {(
              <Switch
                className="shrink-0"
                checked={skill.enabled}
                loading={toggling}
                aria-label={switchLabel}
                onCheckedChange={(enabled) => onToggle(skill, enabled)}
              />
            )}
          </div>
          <DialogDescription className="mt-2.5 line-clamp-2 break-words text-body-sm leading-relaxed text-text-3" title={shown.description}>
            {shown.description}
          </DialogDescription>

          {detail.isError && (
            <p role="alert" className="mt-4 rounded-xl bg-fill-1 p-4 text-body-sm text-text-2">
              {localize('com_skill_center_open_failed')}
            </p>
          )}
          {!detail.isError && shown.bundleMissing && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-fill-1 p-4">
              <p className="text-body-sm text-text-2">{localize('com_skill_center_bundle_missing')}</p>
              {personal && <Button onClick={() => onUpdate(personal)}>{localize('com_skill_center_update')}</Button>}
            </div>
          )}
          {!detail.isError && !shown.bundleMissing && (files.length > 0 || shown.preview || shown.sourceText) && (
            <SkillReader key={shown.id} skill={{ ...shown, files }} />
          )}
          {!detail.isError && !personal && !shown.bundleMissing && !shown.preview && files.length === 0 && !detail.isLoading && (
            <p className="mt-4 rounded-xl bg-fill-1 p-4 text-body-sm text-text-3">{localize('com_skill_center_platform_note')}</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
    <Dialog open={confirmDelete} onOpenChange={(next) => { if (!mutation.isLoading) setConfirmDelete(next); }}>
      <DialogContent close={false}>
        <DialogTitle>{localize('com_skill_center_delete_title')}</DialogTitle>
        <DialogDescription>{localize('com_skill_center_delete_confirm', { name: shown.displayName })}</DialogDescription>
        {error && <p role="alert" className="text-body-sm text-danger">{localize('com_skill_center_delete_failed')}</p>}
        <div className="flex justify-end gap-2">
          <Button color="default" variant="outlined" disabled={mutation.isLoading} onClick={() => setConfirmDelete(false)}>{localize('com_skill_center_cancel')}</Button>
          <Button color="danger" loading={mutation.isLoading} onClick={() => void handleDelete()}>{localize('com_ui_delete')}</Button>
        </div>
      </DialogContent>
    </Dialog>
  </>;
}
