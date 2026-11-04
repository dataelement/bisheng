import type { ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import ArticlePage from './ArticlePage';

const mockArticle = { id: 'article', title: 'Article title', content_html: '<p>Body</p>' };
const localize = (key: string) => key;
jest.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: mockArticle, isLoading: false, isError: false }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => localize, usePrefersMobileLayout: () => true }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/channels', () => ({ getArticleDetailApi: jest.fn() }));
jest.mock('../ArticleList/ArticleList', () => ({ mapToArticle: () => mockArticle }));
jest.mock('~/components/CopyShareLinkButton', () => ({ buildClientShareUrl: (path: string) => path }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('./ArticleDetail', () => ({ ArticleDetail: () => null }));
jest.mock('./AddToKnowledgeModal', () => ({ AddToKnowledgeModal: () => null }));
jest.mock('../AiChat/ArticleAiDock', () => ({ ArticleAiDock: () => null }));
jest.mock('~/utils', () => ({ cn: (...parts: unknown[]) => parts.filter(Boolean).join(' '), copyText: jest.fn() }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => <svg /> }) }));
jest.mock('@bisheng/ui', () => ({ Dropdown: ({ children }: { children: ReactNode }) => children, DropdownItem: () => null }));

function ChannelDestination() {
  return <output>{useLocation().pathname}</output>;
}
function renderArticle() {
  render(<MemoryRouter initialEntries={['/channel/weekly/article/article']}><style>{'.invisible { visibility: hidden; }'}</style><Routes>
    <Route path="/channel/:channelId/article/:articleId" element={<ArticlePage />} />
    <Route path="/channel/:channelId" element={<ChannelDestination />} />
  </Routes></MemoryRouter>);
}

it('synchronizes back and more actions on down/up scroll and returns to the article channel', () => {
  renderArticle();
  const back = screen.getByRole('button', { name: 'com_ui_go_back' });
  const more = screen.getByRole('button', { name: 'com_subscription.channel_settings' });
  const iframe = screen.getByTitle('Article title') as HTMLIFrameElement;
  fireEvent.load(iframe);
  const scroll = (y: number) => {
    Object.defineProperty(iframe.contentWindow, 'scrollY', { configurable: true, value: y });
    fireEvent.scroll(iframe.contentWindow!);
  };
  expect(back).toBeVisible();
  expect(more).toBeVisible();
  scroll(180);
  expect(back).not.toBeVisible();
  expect(more).not.toBeVisible();
  scroll(150);
  expect(back).toBeVisible();
  expect(more).toBeVisible();
  scroll(250);
  expect(back).not.toBeVisible();
  scroll(0);
  expect(back).toBeVisible();
  expect(more).toBeVisible();
  fireEvent.click(back);
  expect(screen.getByRole('status')).toHaveTextContent('/channel/weekly');
});
