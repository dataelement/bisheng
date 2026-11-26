import { SimilarDocumentDialog as SharedSimilarDocumentDialog, type SimilarDocumentDialogProps as SharedDialogProps } from '@bisheng/knowledge';
import { useQueryClient } from '@tanstack/react-query';
import {
  dismissSimilarApi,
  getPendingSimilarFilesApi,
  getSimilarCandidatesApi,
  linkAsNewVersionApi,
  searchDocumentsApi,
} from '~/api/knowledge';
import { showApiError } from '~/api/request';
import { NotificationSeverity } from '~/common';
import { useToastContext } from '~/Providers';

interface SimilarDocumentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spaceId: number;
  restrictToFileIds?: string[];
  onProcessed?: () => void;
}

const services: SharedDialogProps['services'] = {
  getPending: getPendingSimilarFilesApi,
  getRecommendations: getSimilarCandidatesApi,
  searchDocuments: searchDocumentsApi,
  relate: (fileId, documentId) => linkAsNewVersionApi({
    knowledge_file_id: fileId,
    target_document_id: documentId,
  }),
  dismiss: dismissSimilarApi,
};

export function SimilarDocumentDialog({ onProcessed, ...props }: SimilarDocumentDialogProps) {
  const { showToast } = useToastContext();
  const queryClient = useQueryClient();
  return (
    <SharedSimilarDocumentDialog
      {...props}
      services={services}
      onError={showApiError}
      onSuccess={(message) => showToast({ message, severity: NotificationSeverity.SUCCESS })}
      onProcessed={() => {
        void queryClient.invalidateQueries({ queryKey: ['pending-similar', props.spaceId] });
        onProcessed?.();
      }}
    />
  );
}
