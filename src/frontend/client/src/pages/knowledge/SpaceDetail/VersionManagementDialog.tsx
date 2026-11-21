import { VersionManagementDialog as SharedVersionManagementDialog } from '@bisheng/knowledge';
import type { KnowledgeFile } from '~/api/knowledge';
import { showApiError } from '~/api/request';
import { useToastContext } from '~/Providers';
import { clientSimilarDocumentsServices } from './RelateDocumentPanel';

interface VersionManagementDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spaceId: number;
  file: KnowledgeFile | null;
  onLinked?: () => void;
}

export function VersionManagementDialog({ open, onOpenChange, spaceId, file, onLinked }: VersionManagementDialogProps) {
  const { showToast } = useToastContext();
  return <SharedVersionManagementDialog open={open} onOpenChange={onOpenChange} spaceId={spaceId} file={file ? { id: Number(file.id), name: file.name, version_no: file.version_no, user_name: file.user_name } : null} services={clientSimilarDocumentsServices} onLinked={onLinked} onDismissed={onLinked} onError={showApiError} onSuccess={(message) => showToast({ message, status: 'success' })} />;
}
