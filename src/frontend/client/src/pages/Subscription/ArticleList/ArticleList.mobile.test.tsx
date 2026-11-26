import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { Article } from '~/api/channels';
import { ArticleList } from './ArticleList';

const channel = { id: 'weekly', name: 'Weekly' } as Parameters<typeof ArticleList>[0]['channel'];
const mockUnread = jest.fn();
const mockPrefersMobileLayout = jest.fn(() => true);
const mockUseArticleList = jest.fn(() => ({
  articles: [] as Article[], loading: false, hasMore: false, currentPage: 1,
  sourceOptions: [], selectedSources: [], subChannels: [], channelDetail: { name: 'Weekly report' },
  onlyUnread: false, mobileSearchOpen: false,
  handleToggleUnread: mockUnread, setMobileSearchOpen: jest.fn(),
}));
jest.mock('./useArticleList', () => ({ useArticleList: () => mockUseArticleList() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, usePrefersMobileLayout: () => mockPrefersMobileLayout() }));
jest.mock('~/components/illustrations', () => ({ EmptyStateIllustration: () => null }));
jest.mock('~/components/InfiniteScroll', () => ({ InfiniteScroll: ({ children }: React.PropsWithChildren) => children }));
jest.mock('~/components/CopyShareLinkButton', () => ({ CopyShareLinkButton: () => null }));
jest.mock('~/components/ApiRequestFailure', () => ({ ApiRequestFailure: () => null }));
jest.mock('../hooks/useArticleShare', () => ({ useArticleShare: () => ({ handleShare: jest.fn() }) }));
jest.mock('../Article/AddToKnowledgeModal', () => ({ AddToKnowledgeModal: () => null }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: {} }) }));
jest.mock('./ChannelActionsMenu', () => ({ ChannelActionsMenu: () => <button>More actions</button> }));
jest.mock('./ChannelSwitcher', () => ({ ChannelSwitcher: () => <button>Switch channel</button>, SERIF_FONT_STACK: '' }));
jest.mock('./MultiSourceSelect', () => ({ MultiSourceSelect: () => null }));
jest.mock('./SearchInput', () => ({ SearchInput: () => null }));
jest.mock('./TruncatedTabLabel', () => ({ TruncatedTabLabel: () => null }));
jest.mock('~/utils', () => ({ cn: (...parts: unknown[]) => parts.filter(Boolean).join(' ') }));
jest.mock('@bisheng/ui', () => ({ Tabs: () => null, Button: () => null, Tooltip: () => null }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => <svg /> }) }));

it('shows the channel title, returns home instead of opening navigation and removes switching', () => {
  const onSelect = jest.fn();
  render(<MemoryRouter><ArticleList channel={channel} onArticleSelect={jest.fn()} onChannelSelect={onSelect} /></MemoryRouter>);
  expect(screen.getByRole('heading', { name: 'Weekly report' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'com_nav_open_sidebar' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Switch channel' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  expect(onSelect).toHaveBeenCalledWith(null);
  fireEvent.click(screen.getByRole('button', { name: 'com_subscription.show_unread_only' }));
  expect(mockUnread).toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'com_subscription.search_articles_of_interest' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'More actions' })).toBeInTheDocument();
});

it.each([
  { layout: 'desktop browse', mobile: false, selectedArticleId: undefined, bottomDividers: 1, topDividers: 0 },
  { layout: 'desktop reading', mobile: false, selectedArticleId: '1', bottomDividers: 0, topDividers: 2 },
  { layout: 'mobile', mobile: true, selectedArticleId: undefined, bottomDividers: 3, topDividers: 0 },
])('draws one set of dividers in $layout', ({ mobile, selectedArticleId, bottomDividers, topDividers }) => {
  mockPrefersMobileLayout.mockReturnValueOnce(mobile);
  const articles: Article[] = ['1', '2', '3'].map((id) => ({
    id, title: `Article ${id}`, url: '', content: '', sourceName: 'Weekly',
    sourceId: 'weekly', channelId: channel.id, isRead: false,
    publishedAt: '2026-01-01', createdAt: '2026-01-01',
  }));
  mockUseArticleList.mockReturnValueOnce({ ...mockUseArticleList(), articles });
  const { container } = render(
    <MemoryRouter><ArticleList channel={channel} selectedArticleId={selectedArticleId} onArticleSelect={jest.fn()} /></MemoryRouter>,
  );
  expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(3);
  // Check which elements supply the borders, including the old responsive class.
  expect(container.querySelectorAll('.border-b.border-dashed')).toHaveLength(bottomDividers);
  expect(container.querySelectorAll('.border-t.border-dashed')).toHaveLength(topDividers);
  expect(container.querySelector('[class~="max-[767px]:border-b"]')).toBeNull();
});
