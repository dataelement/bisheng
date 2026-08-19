/**
 * F056 AC-08 — an app carrying no home tag lives only under the "uncategorised"
 * tab, which is never the plaza's default once home tags are configured. These
 * tests pin the two properties that make such an app findable anyway:
 * a keyword search spans every category, and a first-page request is never
 * dropped because an earlier one is still in flight.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockGetChatOnlineApi = jest.fn();
const mockGetUncategorized = jest.fn();
const mockRecordUsedAppApi = jest.fn();

jest.mock('~/api/apps', () => ({
  getChatOnlineApi: (...args: unknown[]) => mockGetChatOnlineApi(...args),
  getUncategorized: (...args: unknown[]) => mockGetUncategorized(...args),
  recordUsedAppApi: (...args: unknown[]) => mockRecordUsedAppApi(...args),
}));

jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn() }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks', () => ({
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

jest.mock('./components/AgentNavigation', () => ({
  AgentNavigation: ({
    onCategoryChange,
    searchActive,
  }: {
    onCategoryChange: (id: number | string) => void;
    searchActive?: boolean;
  }) => (
    <div>
      <button data-testid="tab-tagged" onClick={() => onCategoryChange(7)}>
        tagged
      </button>
      <button data-testid="tab-uncategorized" onClick={() => onCategoryChange('uncategorized')}>
        uncategorized
      </button>
      <span data-testid="search-active">{String(!!searchActive)}</span>
    </div>
  ),
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

import ExplorePlaza from './explore';

const PAGE_SIZE = 20;

/** The navigation reports the default tab once its tags land; stubbed as a click. */
async function selectTaggedTab() {
  fireEvent.click(screen.getByTestId('tab-tagged'));
  await waitFor(() => expect(mockGetChatOnlineApi).toHaveBeenCalledWith(1, '', 7, PAGE_SIZE));
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
  mockGetChatOnlineApi.mockResolvedValue({ data: [] });
  mockGetUncategorized.mockResolvedValue({ data: [] });
});

describe('ExplorePlaza search scope', () => {
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
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(1, 'expense', -1, PAGE_SIZE),
    );
    expect(mockGetUncategorized).not.toHaveBeenCalled();
    expect(screen.getByTestId('search-active')).toHaveTextContent('true');
  });

  it('searches across tabs from the uncategorized tab too', async () => {
    render(<ExplorePlaza />);

    fireEvent.click(screen.getByTestId('tab-uncategorized'));
    await waitFor(() => expect(mockGetUncategorized).toHaveBeenCalledWith(1, PAGE_SIZE));

    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });

    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(1, 'expense', -1, PAGE_SIZE),
    );
  });

  it('clears the keyword when a tab is picked, so the tab shows its own apps', async () => {
    render(<ExplorePlaza />);
    await selectTaggedTab();

    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });
    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(1, 'expense', -1, PAGE_SIZE),
    );

    fireEvent.click(screen.getByTestId('tab-uncategorized'));

    await waitFor(() => expect(mockGetUncategorized).toHaveBeenCalledWith(1, PAGE_SIZE));
    expect(screen.getByTestId('search-input')).toHaveValue('');
    expect(screen.getByTestId('search-active')).toHaveTextContent('false');
  });

  it('keeps the search result when the previous request resolves late', async () => {
    render(<ExplorePlaza />);

    let resolveFirstPage: (value: { data: unknown[] }) => void = () => undefined;
    mockGetChatOnlineApi.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirstPage = resolve;
        }),
    );
    mockGetChatOnlineApi.mockResolvedValue({ data: [{ id: '2', name: 'searched app' }] });

    fireEvent.click(screen.getByTestId('tab-tagged'));
    await waitFor(() => expect(mockGetChatOnlineApi).toHaveBeenCalledWith(1, '', 7, PAGE_SIZE));

    // Keyword typed while the tab's own page is still in flight.
    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'expense' } });
    await waitFor(() =>
      expect(mockGetChatOnlineApi).toHaveBeenCalledWith(1, 'expense', -1, PAGE_SIZE),
    );
    resolveFirstPage({ data: [{ id: '1', name: 'stale tab app' }] });

    await waitFor(() => expect(screen.getAllByTestId('agent')).toHaveLength(1));
    expect(screen.getByTestId('agent')).toHaveTextContent('searched app');
  });
});
