import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MessageContent } from './DailyMessageContent';
import MessageMarkDown from '../../BuildPage/flow/FlowChat/MessageMarkDown';

vi.mock('@/components/bs-comp/chatComponent/usePlatformCitationServices', () => ({ usePlatformCitationServices: () => ({ scopeKey: 'synthetic' }) }));
vi.mock('@bisheng/chat/citation-inline', () => ({ InlineCitation: () => null, useCitationDetails: () => ({ details: {}, forbidden: new Set(), expired: new Set(), load: vi.fn() }) }));
vi.mock('@/components/bs-comp/chatComponent/CitationSourceIcon', () => ({ CitationSourceIcon: () => null }));
vi.mock('@/components/bs-comp/chatComponent/CitationDocumentPreviewDrawer', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/chatComponent/citationUtils', () => ({ transformPrivateCitations: (text: string) => ({ transformedContent: text, citationMap: {} }) }));
vi.mock('@/components/voiceFunction/audioPlayButton', () => ({ AudioPlayComponent: () => null }));
vi.mock('@/modals/formModal/chatMessage/codeBlock', () => ({ CodeBlock: () => null }));
vi.mock('@/hooks/useWorkbenchRuntimeConfig', () => ({ useWorkbenchRuntimeConfig: () => ({ data: null }) }));
vi.mock('@/workspace/markdown/Echarts', () => ({ default: () => null }));
vi.mock('@/workspace/markdown/Mermaid', () => ({ default: () => null }));
vi.mock('@bisheng/ui', () => ({ Button: 'button' }));
afterEach(cleanup);

it.each(['audit', 'chat'])('keeps unsafe Markdown URIs inert in the actual %s renderer', (surface) => {
    const text = '[unsafe](javascript:SYNTHETIC) [encoded](jav&#x61;script:SYNTHETIC) [data](data:text/html,SYNTHETIC) [safe](https://example.test) [mail](mailto:qa@example.test) <img src=x onerror="syntheticCanary()">';
    const { container } = render(surface === 'audit' ? <MessageContent text={text} /> : <MessageMarkDown message={text} />);
    const links = [...container.querySelectorAll('a')];
    expect(links.map(link => link.getAttribute('href'))).toEqual(['', '', '', 'https://example.test', 'mailto:qa@example.test']);
    expect(container.querySelector('img, script')).toBeNull();
    expect(container.textContent).toContain('<img src=x onerror="syntheticCanary()">');
});
