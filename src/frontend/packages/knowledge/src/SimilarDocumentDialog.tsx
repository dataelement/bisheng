import { Button, Tooltip, useLoadingIndicatorRenderer } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { DialogShell } from './DialogShell';
import { RelateDocumentPanel } from './RelateDocumentPanel';
import { serviceIdentity } from './serviceIdentity';
import type { SimilarDocumentsServices } from './types';

export interface PendingSimilarFile {
  knowledge_file_id: number;
  file_name: string;
  file_code?: string | null;
  candidate_count: number;
  current_primary_version_no?: number | null;
  primary_uploader_name?: string | null;
}

export interface SimilarDocumentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spaceId: number;
  /** An omitted or empty restriction shows all pending files in the space. */
  restrictToFileIds?: string[];
  services: SimilarDocumentsServices & {
    getPending: (spaceId: number, signal?: AbortSignal) => Promise<PendingSimilarFile[]>;
  };
  onProcessed?: () => void;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
}

interface PendingFileRowProps {
  entry: PendingSimilarFile;
  selected: boolean;
  disabled: boolean;
  onClick: () => void;
}

function PendingFileRow({ entry, selected, disabled, onClick }: PendingFileRowProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={selected}
      onClick={onClick}
      className={[
        'mb-1 flex w-full items-start gap-2 rounded-lg px-3 py-3 text-left transition-colors',
        'hover:bg-fill-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-wait',
        selected ? 'bg-blue-500/[0.07]' : 'bg-transparent',
      ].join(' ')}
    >
      <Outlined.FileSearch aria-hidden className={`mt-0.5 size-3.5 shrink-0 ${selected ? 'text-blue-500' : 'text-text-2'}`} />
      <div className="min-w-0 flex-1">
        <Tooltip content={entry.file_name} side="right">
          <p className={`truncate text-body font-medium leading-5 ${selected ? 'text-blue-500' : 'text-text-1'}`}>
            {entry.file_name}
          </p>
        </Tooltip>
        <p className="mt-1 text-caption text-text-3">
          {t('pending_row_recommend_count', { count: entry.candidate_count })}
        </p>
      </div>
    </button>
  );
}

export function SimilarDocumentDialog(props: SimilarDocumentDialogProps) {
  if (!props.open) return null;
  // A different opening, space or selected batch owns a fresh request lifetime.
  const contextKey = JSON.stringify([props.spaceId, props.restrictToFileIds ?? [], serviceIdentity(props.services)]);
  return <SimilarDocumentSession key={contextKey} {...props} />;
}

function SimilarDocumentSession({
  open,
  onOpenChange,
  spaceId,
  restrictToFileIds,
  services,
  onProcessed,
  onError,
  onSuccess,
}: SimilarDocumentDialogProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  const renderLoading = useLoadingIndicatorRenderer();
  const [pending, setPending] = useState<PendingSimilarFile[]>([]);
  const [selectedFileId, setSelectedFileId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [loadedServices, setLoadedServices] = useState<SimilarDocumentsServices | null>(null);
  const loaded = useRef<SimilarDocumentsServices | null>(null);
  const lifetime = useRef<AbortController>();
  const callbacks = useRef({ onError, onProcessed });
  callbacks.current = { onError, onProcessed };

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    setError(null);
    if (loaded.current !== services) {
      setPending([]);
      setSelectedFileId(null);
      setLoading(true);
    }
    if (!Number.isSafeInteger(spaceId) || spaceId <= 0) {
      setLoadedServices(services);
      setLoading(false);
      return () => controller.abort();
    }
    void services.getPending(spaceId, controller.signal).then(
      (entries) => {
        if (controller.signal.aborted) return;
        loaded.current = services;
        setLoadedServices(services);
        setPending(entries);
        setLoading(false);
      },
      (cause: unknown) => {
        if (controller.signal.aborted) return;
        setLoadedServices(services);
        setError(cause);
        setLoading(false);
        callbacks.current.onError(cause);
      },
    );
    return () => controller.abort();
  }, [spaceId, services, revision]);

  const visiblePending = useMemo(() => {
    if (!restrictToFileIds?.length) return pending;
    const allowed = new Set(restrictToFileIds);
    return pending.filter((entry) => allowed.has(String(entry.knowledge_file_id)));
  }, [pending, restrictToFileIds]);
  const selectedFile = visiblePending.find((entry) => entry.knowledge_file_id === selectedFileId)
    ?? visiblePending[0]
    ?? null;

  const handleProcessed = (fileId: number) => {
    if (lifetime.current?.signal.aborted) return;
    setPending((entries) => entries.filter((entry) => entry.knowledge_file_id !== fileId));
    setSelectedFileId(null);
    setRevision((value) => value + 1);
    callbacks.current.onProcessed?.();
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title={t('similar_dialog_title')}
      closeLabel={t('close')}
      busy={busy}
      className="min-h-[560px] max-h-[80vh] max-w-[960px] overflow-hidden"
      footer={(
        <Button color="default" variant="outlined" disabled={busy} onClick={() => onOpenChange(false)}>
          {t('btn_close')}
        </Button>
      )}
    >
      {loading || loadedServices !== services ? (
        <div className="flex flex-1 items-center justify-center py-16" role="status" aria-label={t('loading')}>
          {renderLoading ? <span aria-hidden>{renderLoading({ className: 'size-10' })}</span> : <Outlined.Loading aria-hidden className="size-6 animate-spin text-text-3" />}
        </div>
      ) : error ? (
        <div role="alert" className="flex flex-1 flex-col items-center justify-center gap-3 py-16 text-body text-text-3">
          <p>{error instanceof Error ? error.message : t('error')}</p>
          <Button color="default" variant="outlined" onClick={() => setRevision((value) => value + 1)}>
            {t('retry')}
          </Button>
        </div>
      ) : visiblePending.length === 0 ? (
        <div className="flex flex-1 items-center justify-center py-16 text-body text-text-3">
          {t('similar_dialog_empty')}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div className="flex w-[260px] shrink-0 flex-col border-r border-border-base bg-fill-1">
            <div className="border-b border-border-base px-5 py-4 text-caption text-text-3">
              {t('similar_dialog_subtitle', { count: visiblePending.length })}
            </div>
            <div className="scrollbar-on-scroll flex-1 overflow-y-auto px-3 py-3">
              {visiblePending.map((entry) => (
                <PendingFileRow
                  key={entry.knowledge_file_id}
                  entry={entry}
                  selected={entry.knowledge_file_id === selectedFile?.knowledge_file_id}
                  disabled={busy || uncertain}
                  onClick={() => setSelectedFileId(entry.knowledge_file_id)}
                />
              ))}
            </div>
          </div>
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
            {selectedFile === null ? (
              <div className="flex flex-1 items-center justify-center text-body text-text-3">
                {t('similar_dialog_right_empty')}
              </div>
            ) : (
              <div className="scrollbar-on-scroll flex-1 overflow-y-auto">
                <RelateDocumentPanel
                  key={selectedFile.knowledge_file_id}
                  spaceId={spaceId}
                  file={{
                    id: selectedFile.knowledge_file_id,
                    name: selectedFile.file_name,
                    file_code: selectedFile.file_code,
                    version_no: selectedFile.current_primary_version_no,
                    user_name: selectedFile.primary_uploader_name,
                    candidate_count: selectedFile.candidate_count,
                  }}
                  services={services}
                  mode="link"
                  disabled={uncertain}
                  className="px-5 py-4"
                  onLinked={() => handleProcessed(selectedFile.knowledge_file_id)}
                  onDismissed={() => handleProcessed(selectedFile.knowledge_file_id)}
                  onBusyChange={setBusy}
                  onUncertain={() => setUncertain(true)}
                  onError={onError}
                  onSuccess={onSuccess}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </DialogShell>
  );
}
