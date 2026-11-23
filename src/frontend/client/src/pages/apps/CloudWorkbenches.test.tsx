import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { AppCenter } from './index';
import { CloudWorkbenches } from './CloudWorkbenches';
import { getCloudWorkbenches } from '~/api/cloudWorkbenches';

let mockUser = { user_id: 1 };
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: mockUser }),
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => false,
  useWorkbenchMenuNames: () => ({ apps: 'Apps' }),
}));
jest.mock('~/api/cloudWorkbenches', () => ({ getCloudWorkbenches: jest.fn() }));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.join(' ') }));
jest.mock('~/components/ModuleHome', () => ({
  MODULE_HOME_FRAME: '',
  MODULE_HOME_COLUMN: '',
  MODULE_HOME_TOOLBAR: '',
  ModuleHomeHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));
jest.mock('@bisheng/ui', () => ({
  ...jest.requireActual('../../../../packages/ui/src/components/StateView/StateView'),
  ...jest.requireActual('../../../../packages/ui/src/components/Illustration/EmptyStateIllustration'),
  ...jest.requireActual('../../../../packages/ui/src/components/Tabs/Tabs'),
  Button: ({ children, asChild, loading, onClick }: { children: React.ReactNode; asChild?: boolean; loading?: boolean; onClick?: () => void }) => asChild ? children : <button disabled={loading} onClick={onClick}>{children}</button>,
}));
jest.mock('./components/AgentCard', () => ({ AgentCard: ({ agent, openLabel }: { agent: { name: string }; openLabel: string }) => <article>{agent.name}<button>{openLabel}</button></article> }));

const getPage = jest.mocked(getCloudWorkbenches);
const board = (id: string) => ({ id, name: id, description: '', entry_url: `https://enterprise.test/apps/${id}/` });
function HistoryBack() {
  const navigate = useNavigate();
  return <button onClick={() => navigate(-1)}>Back</button>;
}

function appsView(path: string) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <HistoryBack />
      <Routes>
        <Route path="/apps" element={<AppCenter />}>
          <Route index element={<p>Recently used apps</p>} />
          <Route path="cloud-workbenches" element={<CloudWorkbenches />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

const view = () => <CloudWorkbenches />;
beforeEach(() => { getPage.mockReset(); mockUser = { user_id: 1 }; });

test('switches app tabs and restores the previous tab on browser back', async () => {
  getPage.mockResolvedValue({ items: [board('hosted-app')], next_cursor: null });
  render(appsView('/apps'));

  const appsTab = screen.getByRole('tab', { name: 'com_app.bisheng_apps' });
  const workbenchesTab = screen.getByRole('tab', { name: 'shared:cloudWorkbenches.title' });
  expect(appsTab).toHaveAttribute('aria-selected', 'true');
  expect(getPage).not.toHaveBeenCalled();

  act(() => {
    fireEvent.mouseDown(workbenchesTab, { button: 0 });
    workbenchesTab.focus();
  });
  expect(workbenchesTab).toHaveAttribute('aria-selected', 'true');
  expect(await screen.findByText('hosted-app')).toBeInTheDocument();
  expect(screen.queryByText('Recently used apps')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(appsTab).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('tabpanel')).toHaveTextContent('Recently used apps');
});

test('shows the illustrated empty state after loading an empty catalog', async () => {
  getPage.mockResolvedValue({ items: [], next_cursor: null });
  render(appsView('/apps/cloud-workbenches'));
  expect(screen.getByRole('tab', { name: 'shared:cloudWorkbenches.title' })).toHaveAttribute('aria-selected', 'true');
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(await screen.findByRole('status')).toHaveTextContent('shared:cloudWorkbenches.empty');
  expect(screen.getByText('shared:cloudWorkbenches.emptyDescription')).toBeInTheDocument();
  expect(screen.getByRole('main').querySelector('[aria-hidden="true"] > svg')).toBeInTheDocument();
});

test('shows usable hosted apps and follows cursor pages without fetching source', async () => {
  getPage.mockResolvedValueOnce({ items: [board('board-a')], next_cursor: 'next' }).mockResolvedValueOnce({ items: [board('board-b')], next_cursor: null });
  render(view());
  expect(await screen.findByText('board-a')).toBeInTheDocument();
  fireEvent.click(screen.getByText('shared:cloudWorkbenches.more'));
  expect(await screen.findByText('board-b')).toBeInTheDocument();
  expect(screen.getAllByRole('article')).toHaveLength(2);
  expect(getPage.mock.calls.map(([cursor]) => cursor)).toEqual([null, 'next']);
});

test('shows a retryable failure instead of an empty catalog when the server is unavailable', async () => {
  getPage.mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({ items: [board('recovered')], next_cursor: null });
  render(view());
  expect(await screen.findByRole('alert')).toHaveTextContent('shared:cloudWorkbenches.failed');
  expect(screen.queryByText('shared:cloudWorkbenches.empty')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('shared:cloudWorkbenches.refresh'));
  expect(await screen.findByText('recovered')).toBeInTheDocument();
});

test('ignores a delayed response from the previous account', async () => {
  let resolveOld: (value: { items: ReturnType<typeof board>[]; next_cursor: null }) => void = () => { throw new Error('Old request not started'); };
  getPage.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; })).mockResolvedValueOnce({ items: [board('my-board')], next_cursor: null });
  const ui = render(view());
  await waitFor(() => expect(getPage).toHaveBeenCalledTimes(1));
  const oldSignal = getPage.mock.calls[0][1];
  mockUser = { user_id: 2 };
  ui.rerender(view());
  expect(await screen.findByText('my-board')).toBeInTheDocument();
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => { resolveOld({ items: [board('other-account-private-board')], next_cursor: null }); });
  expect(screen.queryByText('other-account-private-board')).not.toBeInTheDocument();
});
