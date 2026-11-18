import { RelateDocumentPanel as SharedRelateDocumentPanel, type SimilarDocumentsServices } from '@bisheng/knowledge';
import { dismissSimilarApi, getVersionRecommendationsApi, mergeIntoCurrentApi, searchVersionSourcesApi, type KnowledgeFile, type LinkAsNewVersionResponse } from '~/api/knowledge';
import { showApiError } from '~/api/request';
import { useToastContext } from '~/Providers';

export const clientSimilarDocumentsServices: SimilarDocumentsServices = {
  getRecommendations: getVersionRecommendationsApi,
  searchDocuments: searchVersionSourcesApi,
  relate: (fileId, documentId) => mergeIntoCurrentApi({ current_knowledge_file_id: fileId, source_document_id: documentId }),
  dismiss: dismissSimilarApi,
};

interface RelateDocumentPanelProps {
  spaceId: number;
  fileId: number;
  file: KnowledgeFile;
  onLinked: (response: LinkAsNewVersionResponse) => void;
  onDismissed?: () => void;
  className?: string;
}

export function RelateDocumentPanel({ spaceId, fileId, file, onLinked, onDismissed, className }: RelateDocumentPanelProps) {
  const { showToast } = useToastContext();
  return <SharedRelateDocumentPanel spaceId={spaceId} file={{ id: fileId, name: file.name, version_no: file.version_no, user_name: file.user_name }} services={clientSimilarDocumentsServices} onLinked={onLinked} onDismissed={onDismissed} className={className} onError={showApiError} onSuccess={(message) => showToast({ message, status: 'success' })} />;
}
