export interface SimilarDocumentFile {
  id: number;
  name: string;
  version_no?: number | null;
  user_name?: string | null;
  file_code?: string | null;
  candidate_count?: number;
}

export interface SimilarDocumentCandidate {
  target_document_id: number;
  title: string;
  doc_code?: string | null;
  current_primary_version_no: number;
  similarity: number;
  primary_uploader_name?: string | null;
  primary_upload_time?: string | null;
}

export interface SearchableDocument {
  document_id: number;
  title: string;
  doc_code?: string | null;
  current_primary_version_no: number;
  primary_uploader_name?: string | null;
  primary_upload_time?: string | null;
}

export interface VersionLinkResult {
  document_id: number;
  new_version_no: number;
}

export interface SimilarDocumentsServices {
  getRecommendations: (fileId: number, signal?: AbortSignal) => Promise<SimilarDocumentCandidate[]>;
  searchDocuments: (spaceId: number, keyword: string, fileId: number, signal?: AbortSignal) => Promise<SearchableDocument[]>;
  relate: (fileId: number, documentId: number, signal?: AbortSignal) => Promise<VersionLinkResult>;
  dismiss: (fileId: number, signal?: AbortSignal) => Promise<unknown>;
}

export interface SimilarDocumentEvents {
  onLinked?: (result: VersionLinkResult) => void;
  onDismissed?: () => void;
  onError: (error: unknown) => void;
  onSuccess: (message: string) => void;
  onBusyChange?: (busy: boolean) => void;
  onUncertain?: () => void;
}
