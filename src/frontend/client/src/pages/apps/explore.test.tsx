/**
 * All and keyword search span every category. A first-page request is never
 * dropped because an earlier one is still in flight.
 *
 * Both list endpoints are F027 cursor waterfalls: the first page asks with a
 * `null` cursor and the answer is `{ list, hasMore, nextCursor }`.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetChatOnlineApi = jest.fn();
const mockGetHomeLabelApi = jest.fn();
const mockGetUncategorized = jest.fn();
const mockRecordUsedAppApi = jest.fn();

jest.mock('~/api/apps', () => ({
  getChatOnlineApi: (...args: unknown[]) => mockGetChatOnlineApi(...args),
  getHomeLabelApi: () => mockGetHomeLabelApi(),
  getUncategorized: (...args: unknown[]) => mockGetUncategorized(...args),
  recordUsedAppApi: (...args: unknown[]) => mockRecordUsedAppApi(...args),
}));

jest.mock('react-router-dom', () => ({
  useLocation: () => ({ pathname: '/square' }),
  useNavigate: () => jest.fn(),
}));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: { role: 'user' } }),
  useLocalize: () => (key: string) => key,
  useMediaQuery: () => false,
}));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: undefined }) }));
jest.mock('~/common', () => ({ NotificationSeverity: { SUCCESS: 'success', ERROR: 'error' } }));
jest.mock('~/utils', () => ({
  cn: (...classes: unknown[]) => classes.filter(Boolean).join(' '),
  copyText: jest.fn(),
}));
jest.mock('~/components/ui/Button', () => ({ Button: () => null }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/illustrations', () => ({ EmptyStateIllustration: () => null }));
jest.mock('./appUtils', () => ({ getAppShareUrl: () => '' }));

jest.mock('./components/AgentCard', () => ({
  AgentCard: ({ agent }: { agent: { name: string } }) => <div data-testid="agent">{agent.name}</div>,
}));

jest.mock('./components/MarkLabel', () => ({ __esModule: true, default: () => null }));

jest.mock('./components/AppSearchBar', () => ({
  AppSearchBar: ({ query, onSearch }: { query: string; onSearch: (value: string) => void }) => (
    <input
      data-testid="search-input"
      value={query}
      onChange={(event) => onSearch(event.target.value)}
    />
  ),
}));

import ExplorePlaza from './explore';

const PAGE_SIZE = 20;

async function selectTaggedTab() {
  fireEvent.mouseDown(await screen.findByRole('tab', { name: 'Finance' }));
  await waitFor(() => expect(mockGetChatOnlineApi).toHaveBeenCalledWith(null, '', 7, PAGE_SIZE));
}

beforeAll(() => {
  class IntersectionObserverStub {
    observe() {
      /* no-op */
    }
    unobserve() {
      /* no-op */
    }
    disconnect() {
      /* no-op */
    }
  }
  (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
    IntersectionObserverStub;
});

beforeEach(() => {
  mockGetChatOnlineApi.mockResolvedValue({ list: [], hasMore: false, nextCursor: null });
  mockGetHomeLabelApi.mockResolvedValue({ data: [{ id: 7, name: 'Finance' }] });
  mockGetUncategorized.mockResolvedValue({ list: [], hasMore: false, nextCursor: null });
});

describe('ExplorePlaza search scope', () => {
  it('defaults to All and can return to it from a category', async () => {
    mockGetChatOnlineApi.mockImplementation(async (_cursor, _query, tagId) => ({
      list: tagId === -1
        ? [{ id: '1', name: 'Categorized app' }, { id: '2', name: 'Untagged app' }]
        : [{ id: '1', name: 'Categorized app' }],
      hasMore: false,
      nextCursor: null,
    }));
    render(<ExplorePlaza />);

    await screen.findByText('Untagged app');
    expect(mockGetChatOnlineApi).toHaveBeenNthCalledWith(1, null, '', -1, PAGE_SIZE);
    const allTab = screen.getByRole('tab', { name: 'com_app.all', selected: true });
    expect(screen.getAllByRole('tab')[0]).toBe(allTab);

    await selectTaggedTab();
    await waitFor(() => expect(screen.queryByText('Untagged app')).not.toBeInTheDocument());

    fireEvent.keyDown(allTab, { key: 'Enter' });
    await screen.findByText('Untagged app');
    expect(screen.getByText('Categorized app')).toBeInTheDocument();
    expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(null, '', -1, PAGE_SIZE);
    expect(mockGetUncategorized).not.toHaveBeenCalled();
  });

  it('loads the selected tab through the tag-filtered endpoint', async () => {
    render(<ExplorePlaza />);

    await selectTaggedTab();
    expect(mockGetUncategorized).not.toHaveBeenCalled();
  });

  it('drops the tag filter while a keyword is present so search spans every tab', async () => {
    render(<ExplorePlaza />);
    await selectTaggedTab();

    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });

    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(null, 'expense', -1, PAGE_SIZE),
    );
    expect(mockGetUncategorized).not.toHaveBeenCalled();
    expect(screen.queryByRole('tab', { selected: true })).not.toBeInTheDocument();
  });

  it('searches across tabs from the uncategorized tab too', async () => {
    render(<ExplorePlaza />);

    fireEvent.mouseDown(screen.getByRole('tab', { name: 'com_app_uncategorized' }));
    await waitFor(() => expect(mockGetUncategorized).toHaveBeenCalledWith(null, PAGE_SIZE));

    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });

    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(null, 'expense', -1, PAGE_SIZE),
    );
  });

  it('clears the keyword when a tab is picked, so the tab shows its own apps', async () => {
    render(<ExplorePlaza />);
    await selectTaggedTab();

    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });
    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(null, 'expense', -1, PAGE_SIZE),
    );

    fireEvent.mouseDown(screen.getByRole('tab', { name: 'com_app_uncategorized' }));

    await waitFor(() => expect(mockGetUncategorized).toHaveBeenCalledWith(null, PAGE_SIZE));
    expect(screen.getByTestId('search-input')).toHaveValue('');
    expect(screen.getByRole('tab', { name: 'com_app_uncategorized', selected: true })).toBeInTheDocument();
  });

  it('keeps the search result when the previous request resolves late', async () => {
    render(<ExplorePlaza />);
    const financeTab = await screen.findByRole('tab', { name: 'Finance' });

    let resolveFirstPage: (value: { list: unknown[]; hasMore: boolean; nextCursor: string | null }) => void =
      () => undefined;
    mockGetChatOnlineApi.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirstPage = resolve;
        }),
    );
    mockGetChatOnlineApi.mockResolvedValue({
      list: [{ id: '2', name: 'searched app' }],
      hasMore: false,
      nextCursor: null,
    });

    fireEvent.mouseDown(financeTab);
    await waitFor(() => expect(mockGetChatOnlineApi).toHaveBeenCalledWith(null, '', 7, PAGE_SIZE));

    // Keyword typed while the tab's own page is still in flight.
    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });
    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(null, 'expense', -1, PAGE_SIZE),
    );
    resolveFirstPage({ list: [{ id: '1', name: 'stale tab app' }], hasMore: false, nextCursor: null });

    await waitFor(() => expect(screen.getAllByTestId('agent')).toHaveLength(1));
    expect(screen.getByTestId('agent')).toHaveTextContent('searched app');
  });
});
