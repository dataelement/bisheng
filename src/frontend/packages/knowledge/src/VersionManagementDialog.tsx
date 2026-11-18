import { Button } from '@bisheng/ui';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { DialogShell } from './DialogShell';
import { RelateDocumentPanel } from './RelateDocumentPanel';
import { serviceIdentity } from './serviceIdentity';
import type { SimilarDocumentEvents, SimilarDocumentFile, SimilarDocumentsServices, VersionLinkResult } from './types';

export interface VersionManagementDialogProps extends Omit<SimilarDocumentEvents, 'onBusyChange'> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spaceId: number;
  file: SimilarDocumentFile | null;
  services: SimilarDocumentsServices;
}

export function VersionManagementDialog(props: VersionManagementDialogProps) {
  if (!props.open || !props.file) return null;
  return <VersionManagementDialogContent key={`${props.spaceId}:${props.file.id}:${serviceIdentity(props.services)}`} {...props} file={props.file} />;
}

function VersionManagementDialogContent({ open, onOpenChange, spaceId, file, services, onLinked, onDismissed, onError, onSuccess }: VersionManagementDialogProps & { file: SimilarDocumentFile }) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.version' });
  const [busy, setBusy] = useState(false);
  const handleLinked = (result: VersionLinkResult) => { onLinked?.(result); onOpenChange(false); };
  const handleDismissed = () => { onDismissed?.(); onOpenChange(false); };
  return (
    <DialogShell open={open} onOpenChange={onOpenChange} busy={busy} title={t('dialog_title')} closeLabel={t('close')} className="max-h-[85vh] max-w-[720px]" footer={<Button type="button" color="default" variant="outlined" disabled={busy} onClick={() => onOpenChange(false)}>{t('cancel')}</Button>}>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        <RelateDocumentPanel spaceId={spaceId} file={file} services={services} onLinked={handleLinked} onDismissed={handleDismissed} onError={onError} onSuccess={onSuccess} onBusyChange={setBusy} />
      </div>
    </DialogShell>
  );
}
