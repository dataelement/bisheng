import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ArticleList } from './ArticleList';

const mockUnread = jest.fn();
const mockUseArticleList = jest.fn(() => ({
  articles: [], loading: false, hasMore: false, currentPage: 1,
  sourceOptions: [], selectedSources: [], subChannels: [], channelDetail: { name: 'Weekly report' },
  onlyUnread: false, mobileSearchOpen: false,
  handleToggleUnread: mockUnread, setMobileSearchOpen: jest.fn(),
}));
jest.mock('./useArticleList', () => ({ useArticleList: () => mockUseArticleList() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, usePrefersMobileLayout: () => true }));
jest.mock('~/components/illustrations', () => ({ EmptyStateIllustration: () => null }));
jest.mock('~/components/InfiniteScroll', () => ({ InfiniteScroll: () => null }));
jest.mock('~/components/CopyShareLinkButton', () => ({ CopyShareLinkButton: () => null }));
jest.mock('~/components/ApiRequestFailure', () => ({ ApiRequestFailure: () => null }));
jest.mock('./ArticleCard', () => ({ ArticleCard: () => null }));
jest.mock('./ChannelActionsMenu', () => ({ ChannelActionsMenu: () => <button>More actions</button> }));
jest.mock('./ChannelSwitcher', () => ({ ChannelSwitcher: () => <button>Switch channel</button>, SERIF_FONT_STACK: '' }));
jest.mock('./MultiSourceSelect', () => ({ MultiSourceSelect: () => null }));
jest.mock('./SearchInput', () => ({ SearchInput: () => null }));
jest.mock('./TruncatedTabLabel', () => ({ TruncatedTabLabel: () => null }));
jest.mock('~/utils', () => ({ cn: (...parts: unknown[]) => parts.filter(Boolean).join(' ') }));
jest.mock('@bisheng/ui', () => ({ Tabs: () => null }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => <svg /> }) }));

it('shows the channel title, returns home instead of opening navigation and removes switching', () => {
  const onSelect = jest.fn();
  const channel = { id: 'weekly', name: 'Weekly' } as Parameters<typeof ArticleList>[0]['channel'];
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
