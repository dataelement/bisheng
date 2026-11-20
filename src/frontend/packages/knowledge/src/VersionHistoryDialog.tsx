import { Button } from '@bisheng/ui';
import { CheckCircle, Download, Eye, Loader2, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { DialogShell } from './DialogShell';
import { RelationConfirmation } from './RelationConfirmation';
import { VersionHistoryAction, VersionHistoryStatusBadge, VersionHistorySummary, VersionHistoryTable } from './VersionHistoryTable';
import { versionDialogStyles as styles } from './versionDialogStyles';

export interface VersionHistoryEntry {
  version_id: number;
  version_no: number;
  is_primary: boolean;
  knowledge_file_id: number;
  original_file_name: string;
  file_code?: string | null;
  uploader_name?: string | null;
  upload_time?: string | null;
  status?: number | null;
}

export interface VersionHistoryData {
  title: string;
  doc_code?: string | null;
  current_primary_version_no?: number | null;
  versions: readonly VersionHistoryEntry[];
}

export interface VersionHistoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documentTitle?: string;
  data?: VersionHistoryData;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  unavailable?: ReactNode;
  canManage: boolean;
  canDelete?: (version: VersionHistoryEntry) => boolean;
  canDownload?: (version: VersionHistoryEntry) => boolean;
  onPreview?: (fileId: number, name: string) => void;
  onDownload?: (fileId: number, name: string, signal: AbortSignal) => void | Promise<void>;
  setPrimary: (versionId: number, signal: AbortSignal) => Promise<unknown>;
  deleteVersion: (versionId: number, signal: AbortSignal) => Promise<unknown>;
  onChanged?: (anchorFileId?: number) => void | Promise<unknown>;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
}

type Operation = 'primary' | 'delete';
type PendingAction = { operation: Operation; versionId: number };

export function VersionHistoryDialog(props: VersionHistoryDialogProps) {
  return props.open ? <VersionHistorySession {...props} /> : null;
}

function VersionHistorySession({ onOpenChange, documentTitle, data, loading, error, onRetry, unavailable,
  canManage, canDelete, canDownload, onPreview, onDownload, setPrimary, deleteVersion,
  onChanged, onError, onSuccess }: VersionHistoryDialogProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const lifetime = useRef<AbortController>();
  const writing = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    return () => controller.abort();
  }, []);

  const canSetPrimary = (version: VersionHistoryEntry) => canManage && !version.is_primary && version.status === 2;
  const canDeleteVersion = (version: VersionHistoryEntry) => canManage && !version.is_primary && (canDelete?.(version) ?? true);
  const versions = [...(data?.versions ?? [])].sort((a, b) => a.version_no - b.version_no);
  const target = versions.find(version => version.version_id === pending?.versionId);
  const active = pending && target && !unavailable && !error && !uncertain &&
    (pending.operation === 'primary' ? canSetPrimary(target) : canDeleteVersion(target)) ? pending : null;

  useEffect(() => {
    if (pending && !active) setPending(null);
  }, [pending, active]);

  const handleConfirm = async () => {
    const signal = lifetime.current?.signal;
    if (!active || !target || !signal || signal.aborted || writing.current) return;
    writing.current = true;
    setBusy(true);
    setPending(null);
    const operation = active.operation;
    try {
      await (operation === 'primary' ? setPrimary : deleteVersion)(active.versionId, signal);
      if (signal.aborted) return;
      const remaining = versions.filter(version => version.version_id !== target.version_id);
      const anchor = operation === 'primary' ? target : remaining.find(version => version.is_primary) ?? remaining[0];
      onSuccess(t(`history.feedback.${operation}`));
      await onChanged?.(anchor?.knowledge_file_id);
    } catch (error) {
      if (!signal.aborted) {
        setUncertain(true);
        onError(error);
      }
    } finally {
      writing.current = false;
      if (!signal.aborted) setBusy(false);
    }
  };

  const handleDownload = async (version: VersionHistoryEntry) => {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted || writing.current) return;
    try {
      await onDownload?.(version.knowledge_file_id, version.original_file_name, signal);
    } catch (error) {
      if (!signal.aborted) onError(error);
    }
  };

  return (
    <DialogShell open onOpenChange={onOpenChange} title={t('history.title')} closeLabel={t('close')} appearance="history" busy={busy}
      footer={<Button color="default" variant="outlined" disabled={busy} onClick={() => onOpenChange(false)}>{t('btn_close')}</Button>}>
      <div className={`${styles.body} py-4`}>
        {unavailable || (
          <>
            <VersionHistorySummary documentTitle={data?.title ?? documentTitle} documentCode={data?.doc_code} primaryVersion={data?.current_primary_version_no} />
            {uncertain && <p role="alert" className="mb-4 text-sm text-text-2">{t('history.uncertain')}</p>}
            {loading ? (
              <div role="status" aria-label={t('loading')} className="flex h-32 items-center justify-center">
                <Loader2 className="size-6 animate-spin text-text-3" aria-hidden />
              </div>
            ) : error ? (
              <div role="alert" className="flex min-h-32 items-center justify-center gap-2">
                <span>{error instanceof Error ? error.message : t('error')}</span>
                {onRetry && <Button variant="outlined" onClick={onRetry}>{t('retry')}</Button>}
              </div>
            ) : versions.length === 0 ? (
              <div className="flex h-32 items-center justify-center text-sm text-text-3">{t('history.empty')}</div>
            ) : (
              <VersionHistoryTable rows={versions.map(version => ({
                id: version.version_id,
                versionNumber: version.version_no,
                isPrimary: version.is_primary,
                fileName: version.original_file_name,
                fileCode: version.file_code,
                uploader: version.uploader_name,
                uploadedAt: version.upload_time,
                status: <VersionHistoryStatusBadge status={version.status ?? 0} />,
                actions: (
                  <>
                    {onPreview && <VersionHistoryAction label={t('history.actions.preview')} disabled={busy}
                      onClick={() => onPreview(version.knowledge_file_id, version.original_file_name)}><Eye className="size-4" aria-hidden /></VersionHistoryAction>}
                    {onDownload && (canDownload?.(version) ?? true) && <VersionHistoryAction label={t('history.actions.download')} disabled={busy}
                      onClick={() => void handleDownload(version)}><Download className="size-4" aria-hidden /></VersionHistoryAction>}
                    {canSetPrimary(version) && <VersionHistoryAction label={t('history.actions.primary')} disabled={busy || uncertain} tone="primary"
                      onClick={() => setPending({ operation: 'primary', versionId: version.version_id })}><CheckCircle className="size-4" aria-hidden /></VersionHistoryAction>}
                    {canDeleteVersion(version) && <VersionHistoryAction label={t('history.actions.delete')} disabled={busy || uncertain} tone="danger"
                      onClick={() => setPending({ operation: 'delete', versionId: version.version_id })}><Trash2 className="size-4" aria-hidden /></VersionHistoryAction>}
                  </>
                ),
              }))} />
            )}
          </>
        )}
      </div>
      {active && target && <RelationConfirmation open busy={false}
        title={t(`history.confirm.${active.operation}.title`)}
        description={t(`history.confirm.${active.operation}.description`, { version: target.version_no })}
        onCancel={() => setPending(null)} onConfirm={() => void handleConfirm()} />}
    </DialogShell>
  );
}
