/**
 * The type tabs and keyword share a cursor-paginated list. A first-page
 * request supersedes any earlier request still in flight.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const mockGetChatOnlineApi = jest.fn();
const mockGetHomeLabelApi = jest.fn();
const mockGetUncategorized = jest.fn();
const mockRecordUsedAppApi = jest.fn();
const mockIntersections = new Set<() => void>();

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
  useLocalize: () => (key: string) => key,
  useMediaQuery: () => false,
}));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: undefined }) }));
const mockRuntimeEnabled = jest.fn(() => true);
jest.mock('~/hooks/useAppRuntimeEnabled', () => ({ useAppRuntimeEnabled: () => mockRuntimeEnabled() }));
jest.mock('~/common', () => ({ NotificationSeverity: { SUCCESS: 'success', ERROR: 'error' } }));
jest.mock('~/utils', () => ({
  cn: (...classes: unknown[]) => classes.filter(Boolean).join(' '),
  copyText: jest.fn(),
}));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/illustrations', () => ({ EmptyStateIllustration: () => null }));
jest.mock('./appUtils', () => ({ getAppShareUrl: () => '' }));

jest.mock('./components/AgentCard', () => ({
  AgentCard: ({ agent }: { agent: { name: string } }) => <div data-testid="agent">{agent.name}</div>,
}));

jest.mock('./components/AppSearchBar', () => ({
  AppSearchBar: ({ query, onSearch }: { query: string; onSearch: (value: string) => void }) => (
    <input
      data-testid="search-input"
      value={query}
      onChange={(event) => onSearch(event.target.value)}
    />
  ),
}));

import { ExplorePlaza } from './explore';

const PAGE_SIZE = 20;

function selectTypeTab(name: string) {
  fireEvent.mouseDown(screen.getByRole('tab', { name }));
}

beforeAll(() => {
  class IntersectionObserverStub {
    private intersect: () => void;
    constructor(callback: IntersectionObserverCallback) {
      this.intersect = () => callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      );
    }
    observe() {
      mockIntersections.add(this.intersect);
    }
    unobserve() {
      /* no-op */
    }
    disconnect() {
      mockIntersections.delete(this.intersect);
    }
  }
  (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
    IntersectionObserverStub;
});

beforeEach(() => {
  mockIntersections.clear();
  mockRuntimeEnabled.mockReturnValue(true);
  mockGetChatOnlineApi.mockResolvedValue({ list: [], hasMore: false, nextCursor: null });
  mockGetHomeLabelApi.mockResolvedValue({ data: [{ id: 7, name: 'Finance' }] });
  mockGetUncategorized.mockResolvedValue({ list: [], hasMore: false, nextCursor: null });
});

async function showLoader() {
  await act(async () => {
    for (const intersect of [...mockIntersections]) intersect();
  });
}

describe('ExplorePlaza type tabs', () => {
  it('shows the four types in order, defaults to All types, and can return to it', async () => {
    mockGetChatOnlineApi.mockImplementation(async (_cursor, _keyword, _tagId, _limit, _action, flowType) => ({
      list: flowType === undefined
        ? [{ id: '1', name: 'Hosted app' }, { id: '2', name: 'Assistant app' }]
        : [{ id: '1', name: 'Hosted app' }],
      hasMore: false,
      nextCursor: null,
    }));
    render(<ExplorePlaza />);

    await screen.findByText('Assistant app');
    expect(mockGetChatOnlineApi).toHaveBeenNthCalledWith(1, null, '', -1, PAGE_SIZE, 'visible', undefined);
    const tabList = screen.getByRole('tablist', { name: 'com_app.type_filter' });
    const expectedTypes = [
      'com_app.type_all', 'com_app.type_hosted_app', 'com_app.type_assistant', 'com_app.type_workflow',
    ];
    expect(within(tabList).getAllByRole('tab')).toEqual(
      expectedTypes.map((name) => within(tabList).getByRole('tab', { name })),
    );
    const allTab = within(tabList).getByRole('tab', { name: 'com_app.type_all', selected: true });
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();

    selectTypeTab('com_app.type_hosted_app');
    await waitFor(() => expect(screen.queryByText('Assistant app')).not.toBeInTheDocument());
    expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(null, '', -1, PAGE_SIZE, 'visible', 35);

    fireEvent.keyDown(allTab, { key: 'Enter' });
    await screen.findByText('Assistant app');
    expect(screen.getByText('Hosted app')).toBeInTheDocument();
    expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(null, '', -1, PAGE_SIZE, 'visible', undefined);
    expect(mockGetHomeLabelApi).not.toHaveBeenCalled();
    expect(mockGetUncategorized).not.toHaveBeenCalled();
  });

  it('combines the keyword with the current type and keeps it when switching tabs', async () => {
    render(<ExplorePlaza />);
    selectTypeTab('com_app.type_workflow');
    const search = screen.getByTestId('search-input');
    fireEvent.change(search, { target: { value: '  expense  ' } });

    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(null, 'expense', -1, PAGE_SIZE, 'visible', 10),
    );
    expect(screen.getByRole('tab', { name: 'com_app.type_workflow', selected: true })).toBeInTheDocument();

    selectTypeTab('com_app.type_assistant');
    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(null, 'expense', -1, PAGE_SIZE, 'visible', 5),
    );
    expect(search).toHaveValue('  expense  ');
    expect(screen.getByRole('tab', { name: 'com_app.type_assistant', selected: true })).toBeInTheDocument();
  });

  it('keeps the search result when the previous request resolves late', async () => {
    render(<ExplorePlaza />);
    await screen.findByText('com_app_explore_no_agents');

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

    selectTypeTab('com_app.type_assistant');
    await waitFor(() => expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(null, '', -1, PAGE_SIZE, 'visible', 5));

    // Keyword typed while the tab's own page is still in flight.
    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });
    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(null, 'expense', -1, PAGE_SIZE, 'visible', 5),
    );
    await act(async () => {
      resolveFirstPage({ list: [{ id: '1', name: 'stale tab app' }], hasMore: false, nextCursor: null });
    });

    await waitFor(() => expect(screen.getAllByTestId('agent')).toHaveLength(1));
    expect(screen.getByTestId('agent')).toHaveTextContent('searched app');
  });

  it('hides the hosted-app tab where the runtime layer is unavailable', async () => {
    mockRuntimeEnabled.mockReturnValue(false);
    render(<ExplorePlaza />);
    await screen.findByText('com_app_explore_no_agents');
    expect(screen.queryByRole('tab', { name: 'com_app.type_hosted_app' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'com_app.type_assistant' })).toBeInTheDocument();
  });

  it('shows the type-specific empty state when the tab has no apps', async () => {
    render(<ExplorePlaza />);
    selectTypeTab('com_app.type_assistant');
    expect(await screen.findByText('com_app.type_empty')).toBeInTheDocument();
  });
});

it.each([false, true])('pauses scroll after a request fails and retries the same page (append=%s)', async (append) => {
  mockGetChatOnlineApi.mockClear();
  if (append) {
    mockGetChatOnlineApi.mockResolvedValueOnce({
      list: [{ id: '1', name: 'First app' }], hasMore: true, nextCursor: 'next',
    });
  }
  mockGetChatOnlineApi.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({
    list: [{ id: '2', name: 'Recovered app' }], hasMore: false, nextCursor: null,
  });
  render(<ExplorePlaza />);
  if (append) {
    await screen.findByText('First app');
    await showLoader();
  }

  const retry = await screen.findByRole('button', { name: 'com_ui_retry' });
  await showLoader();
  expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(append ? 2 : 1);
  if (append) expect(screen.getByText('First app')).toBeTruthy();

  fireEvent.click(retry);
  await screen.findByText('Recovered app');
  expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith(append ? 'next' : null, '', -1, PAGE_SIZE, 'visible', undefined);
});

describe('ExplorePlaza failed pages', () => {
  beforeEach(() => {
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  it('stops automatic requests after 25008 and retries only when asked', async () => {
    mockGetChatOnlineApi.mockRejectedValue(Object.assign(new Error('Projection unavailable'), { status_code: 25008 }));
    render(<ExplorePlaza />);
    await screen.findByRole('alert');
    expect(screen.queryByText('com_app_explore_no_agents')).not.toBeInTheDocument();
    expect(screen.queryByText('com_app_explore_loading_more')).not.toBeInTheDocument();
    for (let n = 0; n < 3; n++) await showLoader();
    expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(1);

    mockGetChatOnlineApi.mockResolvedValue({ list: [{ id: 'own', name: 'Own app' }], hasMore: false, nextCursor: null });
    fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
    await screen.findByText('Own app');
    expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('keeps existing cards and retries the same cursor after an append fails', async () => {
    mockGetChatOnlineApi.mockResolvedValueOnce({
      list: [{ id: '1', name: 'First app' }], hasMore: true, nextCursor: 'page-2',
    }).mockRejectedValue(new Error('Network unavailable'));
    render(<ExplorePlaza />);
    await screen.findByText('First app');
    await showLoader();
    await screen.findByRole('alert');
    expect(screen.getByText('First app')).toBeInTheDocument();
    for (let n = 0; n < 3; n++) await showLoader();
    expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(2);

    mockGetChatOnlineApi.mockResolvedValue({
      list: [{ id: '2', name: 'Second app' }], hasMore: false, nextCursor: null,
    });
    fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
    await screen.findByText('Second app');
    expect(screen.getAllByTestId('agent')).toHaveLength(2);
    expect(mockGetChatOnlineApi).toHaveBeenLastCalledWith('page-2', '', -1, PAGE_SIZE, 'visible', undefined);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('allows changing type after the first page fails', async () => {
    mockGetChatOnlineApi.mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValue({
      list: [{ id: '2', name: 'Assistant app' }], hasMore: false, nextCursor: null,
    });
    render(<ExplorePlaza />);
    await screen.findByRole('alert');
    selectTypeTab('com_app.type_assistant');
    await screen.findByText('Assistant app');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each([
    { list: [], hasMore: true, nextCursor: 'page-2' },
    { list: [{ id: '1', name: 'App' }], hasMore: true, nextCursor: null },
  ])('stops when the response cannot advance pagination: %j', async (response) => {
    mockGetChatOnlineApi.mockResolvedValue(response);
    render(<ExplorePlaza />);
    await screen.findByRole('alert');
    await showLoader();
    expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(1);
  });

  it('stops when an append returns its input cursor', async () => {
    mockGetChatOnlineApi.mockResolvedValue({
      list: [{ id: '1', name: 'First app' }], hasMore: true, nextCursor: 'page-2',
    });
    render(<ExplorePlaza />);
    await screen.findByText('First app');
    await showLoader();
    await screen.findByRole('alert');
    await showLoader();
    expect(screen.getAllByTestId('agent')).toHaveLength(1);
    expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(2);
  });

  it('does not replace a newer search with an old request failure', async () => {
    let rejectFirst: (reason: Error) => void = () => undefined;
    mockGetChatOnlineApi.mockImplementationOnce(() => new Promise((_, reject) => { rejectFirst = reject; }));
    render(<ExplorePlaza />);
    await waitFor(() => expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(1));
    mockGetChatOnlineApi.mockResolvedValue({
      list: [{ id: '2', name: 'Search result' }], hasMore: false, nextCursor: null,
    });
    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'search' } });
    await screen.findByText('Search result');
    await act(async () => { rejectFirst(new Error('Old request failed')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Search result')).toBeInTheDocument();
  });

  it('keeps the current append locked when a previous filter finishes late', async () => {
    type Page = { list: { id: string; name: string }[]; hasMore: boolean; nextCursor: string | null };
    let resolveOld: (page: Page) => void = () => undefined;
    let resolveCurrent: (page: Page) => void = () => undefined;
    mockGetChatOnlineApi
      .mockResolvedValueOnce({ list: [{ id: '1', name: 'Old result' }], hasMore: true, nextCursor: 'old-page' })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ list: [{ id: '2', name: 'New result' }], hasMore: true, nextCursor: 'new-page' })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveCurrent = resolve; }));
    render(<ExplorePlaza />);
    await screen.findByText('Old result');
    await showLoader();
    selectTypeTab('com_app.type_workflow');
    await screen.findByText('New result');
    await showLoader();
    expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(4);
    expect(mockGetChatOnlineApi).toHaveBeenNthCalledWith(3, null, '', -1, PAGE_SIZE, 'visible', 10);
    expect(mockGetChatOnlineApi).toHaveBeenNthCalledWith(4, 'new-page', '', -1, PAGE_SIZE, 'visible', 10);
    await act(async () => {
      resolveOld({ list: [{ id: '3', name: 'Stale append' }], hasMore: false, nextCursor: null });
    });
    expect(screen.getByText('com_app_explore_loading_more')).toBeInTheDocument();
    await showLoader();
    expect(mockGetChatOnlineApi).toHaveBeenCalledTimes(4);
    await act(async () => {
      resolveCurrent({ list: [{ id: '4', name: 'Current append' }], hasMore: false, nextCursor: null });
    });
    expect(screen.getByText('Current append')).toBeInTheDocument();
    expect(screen.queryByText('Stale append')).not.toBeInTheDocument();
  });
});
