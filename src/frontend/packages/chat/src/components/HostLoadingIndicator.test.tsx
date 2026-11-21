import { LoadingIndicatorProvider } from '@bisheng/ui';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { CitationDocumentPreview } from '../citations/CitationDocumentPreview';
import { CitationReferenceCard } from '../citations/CitationReferenceCard';
import type { CitationReferenceItem, CitationServices } from '../citations/types';
import { CitationPreviewCard } from '../content/CitationPreviewCard';
import { DiagramBlock } from '../content/DiagramBlock';
import { MarkdownServicesContext } from '../content/MarkdownServices';
import type { MarkdownServices } from '../content/types';
import type { ChatMessage } from '../core/types';
import { ConversationMessages } from './ConversationMessages';
import { MessageBubble, ReasoningDetails } from './MessageBubble';
import { WorkflowFileField } from './WorkflowFileField';

afterEach(cleanup);

const labels = { confirm: 'Confirm', confirmed: 'Confirmed', thinking: 'Thinking', completed: 'Done' };
const localize = (key: string) => key;

function Host({ children }: { children: ReactNode }) {
  return <LoadingIndicatorProvider renderIndicator={({ className }) => <img alt="" data-testid="host-loading" className={className} />}>
    {children}
  </LoadingIndicatorProvider>;
}

function pendingRun(category: string): ChatMessage {
  return { key: category, kind: 'run', category, text: '', reasoning: '', payload: { name: category }, files: [], final: false, raw: {}, issues: [] };
}

function PendingMessages({ onPick }: { onPick: () => void }) {
  return <>
    <ReasoningDetails text="Reasoning content" pending labels={labels} />
    <MessageBubble pending />
    <ConversationMessages messages={[pendingRun('node_run'), pendingRun('tool_run')]} canExecute labels={labels} slots={{ content: text => text }} />
    <WorkflowFileField loading placeholder="Upload" onClick={onPick} />
  </>;
}

it('uses host artwork for every pending chat indicator while retaining streaming labels and upload guards', () => {
  const onPick = vi.fn();
  const { container } = render(<Host><PendingMessages onPick={onPick} /></Host>);
  expect(screen.getAllByTestId('host-loading')).toHaveLength(5);
  expect(container.querySelector('.animate-spin')).toBeNull();
  expect(screen.getByText('Thinking')).toBeTruthy();
  expect(screen.getByText('Reasoning content')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
  expect(onPick).not.toHaveBeenCalled();
});

it('keeps default client indicators when no host renderer is present', () => {
  const { container } = render(<PendingMessages onPick={vi.fn()} />);
  expect(screen.queryByTestId('host-loading')).toBeNull();
  expect(container.querySelectorAll('.animate-spin')).toHaveLength(5);
  expect(screen.getByText('Thinking')).toBeTruthy();
});

const item: CitationReferenceItem = {
  key: 'source',
  data: { label: 1, ref: 'source', type: 'knowledgeSearch', groupKey: '', chunkId: '', citationId: 'source', itemId: '' },
};
const detail = { citationId: 'source', type: 'knowledgeSearch', sourcePayload: { documentName: 'report.pdf', fileType: 'pdf' } };

function PendingPreviews() {
  const citationServices: CitationServices = {
    scopeKey: 'loading-test', localize,
    getCitationDetail: async () => detail,
    resolveCitationDetails: async () => [detail],
    getCitationUnresolvedReason: () => undefined,
    resolveDocumentUrls: () => new Promise<never>(() => {}),
    download: vi.fn(), openArticle: vi.fn(),
  };
  const markdownServices: MarkdownServices = {
    localize, getCitationDetail: citationServices.getCitationDetail,
    resolveCitationDetails: citationServices.resolveCitationDetails,
    getCitationUnresolvedReason: () => undefined,
    copyText: vi.fn(), renderDocumentPreview: () => null,
    loadDiagramLibrary: () => new Promise<never>(() => {}),
  };
  return <MarkdownServicesContext.Provider value={markdownServices}>
    <CitationReferenceCard item={item} localize={localize} detail={null} isLoading hasError={false} onOpenDocumentPreview={vi.fn()} />
    <CitationPreviewCard preview={null} isLoading error={false} />
    <CitationDocumentPreview preview={{ detail }} services={citationServices} renderFile={() => null} />
    <DiagramBlock language="mermaid" code="graph TD; A-->B" />
  </MarkdownServicesContext.Provider>;
}

const loadingLabels = [
  'com_message.source_loading', 'shared:app_chat.citation.loading',
  'shared:citations.com_citation.preview_loading', 'shared:app_chat.loading',
];

it('gives host citation and diagram loaders accessible labels without visible loading text', () => {
  render(<Host><PendingPreviews /></Host>);
  expect(screen.getAllByTestId('host-loading')).toHaveLength(4);
  for (const label of loadingLabels) {
    expect(screen.getByRole('status', { name: label })).toBeTruthy();
    expect(screen.queryByText(label)).toBeNull();
  }
});

it('preserves client citation and diagram loading copy without a host override', () => {
  render(<PendingPreviews />);
  expect(screen.queryByTestId('host-loading')).toBeNull();
  for (const label of loadingLabels) expect(screen.getByText(label)).toBeTruthy();
});
