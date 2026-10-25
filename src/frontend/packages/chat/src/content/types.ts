import type { ComponentType, ReactNode, MouseEvent, RefObject } from 'react';
export type ChatLocalize = (key: string, options?: Record<string, unknown>) => string;
export interface ChatCitationItem {
  itemId?: string; chunkId?: string; chunkIndex?: number; content?: string; snippet?: string; title?: string;
  bbox?: string | null; page?: number; documentName?: string; fileName?: string; filename?: string; file_name?: string;
}
export interface ChatCitationPayload {
  url?: string; title?: string; snippet?: string; content?: string; source?: string; sourceUrl?: string;
  previewUrl?: string; downloadUrl?: string; knowledgeName?: string; documentName?: string;
  fileName?: string; filename?: string; file_name?: string; fileType?: string; datePublished?: string; articleDocId?: string; siteIcon?: string;
  date?: string; documentId?: string | number; page?: number; items?: ChatCitationItem[];
  [key: string]: unknown;
}
export interface ChatCitation { citationId: string; type: string; itemId?: string | null; sourcePayload?: ChatCitationPayload }
export interface CitationDisplayData { label: number; ref: string; type: string; groupKey: string; chunkId: string; citationId: string; itemId: string }
export interface CitationPreview { title: string; snippet: string; sourceName: string; sourceMeta: string; link?: string; type: string }
export type { PreviewPdfBBox as CitationPdfBBox } from '@bisheng/file-viewers/types';
export type CitationDetailLoader = (id: string) => Promise<ChatCitation | null>;
export interface CitationDocumentPreviewState { detail: ChatCitation; itemId?: string; itemIds?: string[]; locateChunk?: boolean }
export interface CitationReferencesDesktopPayload {
  messageId?: string; content: string; webContent?: ChatCitationPayload[];
  citations?: ChatCitation[] | null; referenceItems: never[]; initialDocumentPreview?: CitationDocumentPreviewState | null;
}
export interface CitationSourceIconProps { detail?: ChatCitation | null; preview?: CitationPreview | null; type?: string; ragIconVariant?: 'document' | 'knowledge'; clipAsCircle?: boolean }
export interface MarkdownCodeProps { language: string; code: string; inline: boolean; className?: string; codeRef?: RefObject<HTMLElement> }
export interface MarkdownServices {
  localize: ChatLocalize;
  latexParsing?: boolean;
  isMobileLayout?: boolean;
  finePointer?: boolean;
  getCitationDetail: CitationDetailLoader;
  resolveCitationDetails: (ids: string[]) => Promise<ChatCitation[]>;
  getCitationUnresolvedReason: (id: string) => 'expired' | 'forbidden' | undefined | null;
  SourceIcon?: ComponentType<CitationSourceIconProps>;
  copyText: (text: string) => void | Promise<unknown>;
  renderCodeActions?: (props: MarkdownCodeProps) => ReactNode;
  loadDiagramLibrary: (kind: 'mermaid' | 'echarts') => Promise<unknown>;
  diagramTitle?: string;
  renderArtifact?: (props: Record<string, unknown>) => ReactNode;
  onLinkClick?: (href: string, event: MouseEvent<HTMLAnchorElement>) => void | Promise<void>;
  renderDocumentPreview: (preview: CitationDocumentPreviewState | null, onClose: () => void) => ReactNode;
}
