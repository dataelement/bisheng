import { type ReactNode } from 'react';
import { Citation } from './Citation';
import type { ChatCitation, ChatCitationPayload, CitationDetailLoader, CitationDisplayData } from './types';
export interface CitationTextProps {
  scope: string;
  children: ReactNode;
  webContent?: ChatCitationPayload[];
  citations?: ChatCitation[] | null;
  citationMap: Record<string, CitationDisplayData>;
  details: Record<string, ChatCitation>;
  forbidden: Set<string>;
  expired: Set<string>;
  load: CitationDetailLoader;
  activeKey: string | null;
  onActiveKeyChange: (key: string | null) => void;
  onClose: (key: string) => void;
  onOpen: (detail: ChatCitation, itemId?: string, locateChunk?: boolean) => void;
  finePointer: boolean;
}
export function CitationText({ scope, children, webContent, citations, citationMap, details, forbidden, expired, load, activeKey, onActiveKeyChange, onClose, onOpen, finePointer }: CitationTextProps) {
  if (typeof children !== 'string') return <>{children}</>;
  const nodes: ReactNode[] = []; let previous = 0;
  for (const match of children.matchAll(/\[citation:(\d+)\]|\[citationref:([^\]]+)\]/g)) {
    const offset = match.index ?? 0;
    if (offset > previous) nodes.push(children.slice(previous, offset));
    const label = Number(match[1]);
    const detail = label ? citations?.[label - 1] : undefined;
    const legacy = label && webContent?.[label - 1];
    const data: CitationDisplayData | undefined = match[2] ? citationMap[match[2]] : legacy ? {
      label, ref: `citation:${label}`, type: 'web', groupKey: String(label), chunkId: String(label), citationId: `citation:${label}`, itemId: String(label),
    } : detail ? {
      label, ref: `citation:${label}`, type: detail.type || 'knowledgeSearch', groupKey: detail.citationId,
      chunkId: String(detail.itemId || detail.sourcePayload?.items?.[0]?.itemId || label), citationId: detail.citationId,
      itemId: String(detail.itemId || detail.sourcePayload?.items?.[0]?.itemId || label),
    } : undefined;
    if (data) {
      const key = `${scope}:${offset}`;
      nodes.push(<Citation key={key} data={data} webContent={webContent}
        initialDetail={details[data.citationId] ?? detail} initialNotPermitted={forbidden.has(data.citationId)} initialExpired={expired.has(data.citationId)}
        loadCitationDetail={load} popoverKey={key} activePopoverKey={activeKey} onActivePopoverKeyChange={onActiveKeyChange}
        onClosePopover={onClose} onOpenDocumentPreview={onOpen} citationPreviewUsesHover={finePointer}>{data.label}</Citation>);
    }
    previous = offset + match[0].length;
  }
  if (previous < children.length) nodes.push(children.slice(previous));
  return <>{nodes}</>;
}
