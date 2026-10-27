import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ChatMarkdown } from './ChatMarkdown';
import type { MarkdownServices } from './types';
import { useMarkdownServices } from './MarkdownServices';
afterEach(cleanup);
it('owns an isolated client-style scope and preserves the client code bar and double-click selection', () => {
  const { container } = render(<ChatMarkdown services={services()} content={'Inline `value`\n\n```javascript\nconst value = 1;\n```'} />);
  expect(container.querySelector('.bs-mkdown.bisheng-chat-markdown')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'shared:app_chat.copy_code' }).textContent).toContain('shared:app_chat.copy_code');
  expect(container.querySelector('code.hljs.language-javascript')).toBeTruthy();
  const inline = screen.getByText('value', { selector: 'code' });
  fireEvent.doubleClick(inline);
  expect(window.getSelection()?.toString()).toBe('value');
});
it('uses client media defaults and reacts to viewport changes without host configuration', () => {
  const listeners = new Map<string, (event: { matches: boolean }) => void>();
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('pointer: fine'),
    addEventListener: (_: string, callback: (event: { matches: boolean }) => void) => listeners.set(query, callback), removeEventListener: vi.fn() }));
  function Probe() { const config = useMarkdownServices(); return <output>{String(config.isMobileLayout)}:{String(config.finePointer)}:{String(config.latexParsing)}</output>; }
  const api = services(); api.renderDocumentPreview = () => <Probe />;
  render(<ChatMarkdown services={api} content="Text" />);
  expect(screen.getByRole('status').textContent).toBe('false:true:true');
  act(() => listeners.get('(max-width: 767px)')?.({ matches: true }));
  expect(screen.getByRole('status').textContent).toBe('true:true:true');
  cleanup(); vi.unstubAllGlobals();
});
function services(): MarkdownServices {
  return { localize: key => key, copyText: vi.fn(), getCitationDetail: vi.fn().mockResolvedValue(null), resolveCitationDetails: vi.fn().mockResolvedValue([]),
    getCitationUnresolvedReason: () => 'forbidden', renderDocumentPreview: vi.fn().mockReturnValue(null), loadDiagramLibrary: vi.fn().mockRejectedValue(new Error('missing runtime')) };
}
it('renders headings, tables, literal line breaks and safe text without application providers', () => {
  const { container } = render(<ChatMarkdown services={services()} content={'# Title\n\n| A | B |\n| - | - |\n| a<br>b | c |\n\n<script>alert(1)</script>'} />);
  expect(screen.getByRole('heading', { name: 'Title' })).toBeTruthy();
  expect(screen.getByRole('table')).toBeTruthy(); expect(container.querySelector('br')).toBeTruthy();
  expect(container.querySelector('script')).toBeNull();
});
it('copies highlighted code as source text', () => {
  const api = services();
  render(<ChatMarkdown services={api} content={'```javascript\nconst value = 1;\n```'} />);
  fireEvent.click(screen.getByRole('button', { name: 'shared:app_chat.copy_code' }));
  expect(api.copyText).toHaveBeenCalledWith('const value = 1;');
});
it('keeps an already forbidden citation inert without resolving it again', async () => {
  const api = services();
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
  render(<ChatMarkdown services={api} content={'Answer\ue200knowledgesearch_file:1\ue202'} />);
  await waitFor(() => expect(api.resolveCitationDetails).not.toHaveBeenCalled());
  fireEvent.click(screen.getByText('1'));
  await screen.findByText('shared:app_chat.citation.no_permission');
  expect(api.getCitationDetail).not.toHaveBeenCalled();
  expect(api.renderDocumentPreview).toHaveBeenLastCalledWith(null, expect.any(Function));
  vi.unstubAllGlobals();
});

it.each([
  { name: 'backtick fence', source: '```python\ndef bubble_sort(arr):\n    return arr\n```', code: 'def bubble_sort(arr):\n    return arr\n' },
  { name: 'tilde fence with a deliberate blank line', source: '~~~python\nx = 1\n\nprint(x)\n~~~', code: 'x = 1\n\nprint(x)\n' },
  { name: 'unfinished streaming fence', source: '```python\nx = 1\nprint(x)', code: 'x = 1\nprint(x)\n' },
  { name: 'indented block', source: '    x = 1\n    print(x)', code: 'x = 1\nprint(x)\n' },
])('preserves exact code lines and copied content for $name', ({ source, code }) => {
  const api = services();
  const { container } = render(<ChatMarkdown services={api} content={source} />);
  expect(container.querySelector('code.hljs')?.textContent).toBe(code);
  fireEvent.click(screen.getByRole('button', { name: 'shared:app_chat.copy_code' }));
  expect(api.copyText).toHaveBeenCalledWith(code.trim());
});
it('keeps prose line breaks, list structure and GFM table cells without rewriting the source', () => {
  const { container } = render(<ChatMarkdown services={services()} content={'First line\nSecond line\n\n- One\n- Two\n\n| A | B |\n| - | - |\n| one | two |'} />);
  const paragraph = container.querySelector('p');
  expect(paragraph?.textContent).toBe('First line\nSecond line');
  expect(paragraph?.className).toContain('whitespace-pre-wrap');
  expect(screen.getAllByRole('listitem')).toHaveLength(2);
  expect(screen.getByRole('table')).toBeTruthy();
});
