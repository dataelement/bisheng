import type { PreviewResource, PreviewPdfBBox } from '@bisheng/file-viewers/types';
import type { ChatCitation, ChatLocalize, CitationDisplayData, CitationPreview } from '../content/types';
export type { ChatCitation, ChatCitationPayload, ChatCitationItem, ChatLocalize, CitationDisplayData, CitationPreview, CitationDocumentPreviewState, CitationDetailLoader } from '../content/types';
export type CitationPdfBBox = PreviewPdfBBox;
export interface CitationReferenceItem { key: string; data: CitationDisplayData; itemIds?: string[]; detail?: ChatCitation | null; legacyPreview?: CitationPreview | null }
export interface CitationServices {
  scopeKey: string;
  getCitationDetail: (id: string) => Promise<ChatCitation | null>;
  resolveCitationDetails: (ids: string[]) => Promise<ChatCitation[]>;
  getCitationUnresolvedReason: (id: string) => 'expired' | 'forbidden' | undefined | null;
  resolveDocumentUrls: (detail: ChatCitation) => Promise<PreviewResource>;
  download: (url: string, fileName: string) => void | Promise<void>;
  openArticle: (url: string) => void;
  localize: ChatLocalize;
}
