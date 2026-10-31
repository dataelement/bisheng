import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import type { ComponentProps } from 'react';
import Knowledge from './index';
import MainLayout from '~/layouts/MainLayout';
import { AliveScope } from 'react-activation';
import { KnowledgeSpaceSections as MockKnowledgeSpaceSections } from './sidebar/KnowledgeSpaceSections';
import { KnowledgeSpaceHeader as MockKnowledgeSpaceHeader } from './SpaceDetail/KnowledgeSpaceHeader';
import { SpaceRole, SpaceSortType as MockSpaceSortType, VisibilityType, type KnowledgeSpace } from '~/api/knowledge';

jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => true }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
jest.mock('~/api/apps', () => ({ getBysConfigApi: async () => ({ data: {} }) }));
jest.mock('~/components/Chat/Input/AgentToolSelector', () => ({ useAgentToolPreferences: () => undefined }));
jest.mock('~/layouts/DesktopShellBridge', () => ({ DesktopShellBridge: () => null }));
jest.mock('~/layouts/WorkbenchAccessGuard', () => ({ __esModule: true, default: () => null }));
jest.mock('~/layouts/WorkbenchSidebar', () => ({ WorkbenchSidebar: () => null }));
jest.mock('~/layouts/UserPopMenu', () => ({ UserPopMenu: () => null }));
jest.mock('~/layouts/useWorkbenchNavLinks', () => ({ useWorkbenchNavLinks: () => ({ links: [] }) }));

const mockSpaces: KnowledgeSpace[] = ['department', 'created', 'joined'].map((id) => ({
  id, name: `${id} space`, role: SpaceRole.MEMBER, visibility: VisibilityType.PUBLIC,
} as KnowledgeSpace));
jest.mock('~/api/knowledge', () => ({
  ...jest.requireActual('~/api/knowledge'),
  getMineSpacesApi: jest.fn(async () => [mockSpaces[1]]),
  getJoinedSpacesApi: jest.fn(async () => [mockSpaces[2]]),
  getDepartmentSpacesApi: jest.fn(async () => [mockSpaces[0]]),
  getSpaceInfoApi: jest.fn(async (id: string) => mockSpaces.find((space) => space.id === id)),
}));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useWorkbenchMenuNames: () => ({ knowledge: 'Knowledge' }), usePrefersMobileLayout: () => false, useScrollRevealRef: () => ({ current: null }), useAuthContext: () => ({ user: { id: 'user' }, isUserLoading: false, logout: jest.fn() }) }));
jest.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: { id: 'user', plugins: ['knowledge_space'] }, isUserLoading: false }) }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useEffectiveQuota: () => ({ isOverQuota: () => false }) }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }), useConfirm: () => jest.fn() }));
jest.mock('recoil', () => ({ useRecoilState: () => jest.requireActual('react').useState({}), useRecoilValue: () => ({}), useSetRecoilState: () => jest.fn() }));
jest.mock('~/store', () => ({ __esModule: true, default: { mobileSystemMenuOpenState: {} } }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: {} }));
jest.mock('react-activation', () => ({ __esModule: true, ...jest.requireActual('react-activation'), useActivate: () => undefined, useUnactivate: () => undefined }));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.filter(Boolean).join(' ') }));
jest.mock('~/components/SidebarListMoreMenu', () => ({ knowledgeSpaceDropdownSurfaceClassName: '' }));
jest.mock('./sidebar/SectionHeader', () => ({ SectionHeader: () => null }));
jest.mock('./KnowledgeSpacePreviewDrawer', () => ({ KnowledgeSpacePreviewDrawer: () => null }));
jest.mock('./KnowledgeSquare', () => ({ __esModule: true, default: () => null }));
jest.mock('./SpaceDetail/AiChat/KnowledgeAiBottomDock', () => ({ KnowledgeAiBottomDock: () => null }));
jest.mock('./SpaceDetail/SpaceBreadcrumb', () => ({ SpaceBreadcrumb: () => null }));
jest.mock('~/components/CopyShareLinkButton', () => ({ CopyShareLinkButton: () => null }));
jest.mock('./SpaceDetail/SpaceActionMenuItems', () => ({ SpaceActionMenuItems: () => null, getSpaceActionFlags: () => ({ hasAny: false }) }));
jest.mock('./hooks/useFileUpload', () => ({ useFileUpload: () => ({ uploadingFiles: [], duplicateFiles: [] }) }));
jest.mock('./hooks/useFileManager', () => ({
  useFileManager: () => {
    const { folderId } = jest.requireActual('react-router-dom').useParams();
    return { files: [], currentPath: folderId ? [{ id: folderId, name: 'Folder' }] : [], currentFolderId: folderId, loadFiles: jest.fn() };
  },
}));
// Keep real page navigation, home, Segmented and detail Back; isolate data-heavy children.
jest.mock('./sidebar/KnowledgeSpaceSidebar', () => ({
  KnowledgeSpaceSidebar: ({ onSpaceSelect }: { onSpaceSelect: (space: KnowledgeSpace) => void }) => (
    <MockKnowledgeSpaceSections
      sections={(['department', 'created', 'joined'] as const).map((type, index) => ({
        type, title: type, spaces: [mockSpaces[index]], collapsed: false, onToggle: jest.fn(), sortValue: MockSpaceSortType.UPDATE_TIME,
      }))}
      sortOptions={[]} onSortChange={jest.fn()}
      renderSpaceItem={(space) => <button key={space.id} onClick={() => onSpaceSelect(space)}>{space.name}</button>}
      onCreateSpace={jest.fn()} compactMode={false} mobilePageMode pageGrid
    />
  ),
}));
jest.mock('./SpaceDetail', () => ({
  KnowledgeSpaceContent: (props: ComponentProps<typeof MockKnowledgeSpaceHeader>) => (
    <><MockKnowledgeSpaceHeader {...props} selectedCount={0} />
      <button onClick={() => props.onNavigateFolder('folder-1')}>Open folder</button></>
  ),
}));
// These routes use request metadata only; jsdom supplies no Fetch Request.
class NavigationRequest {
  constructor(public url: string, public init: RequestInit) {}
  get signal() { return this.init.signal; }
  get method() { return this.init.method || 'GET'; }
}
Object.defineProperty(globalThis, 'Request', { configurable: true, value: NavigationRequest });

function setup(path = '/knowledge') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } });
  const router = createMemoryRouter([{ element: <AliveScope><Outlet /></AliveScope>, children: [{ element: <MainLayout />, children: [
    { path: '/before', element: <div>Previous page</div> },
    { path: '/knowledge', element: <Knowledge /> },
    { path: '/knowledge/space/:spaceId', element: <Knowledge /> },
    { path: '/knowledge/space/:spaceId/folder/:folderId', element: <Knowledge /> },
  ] }] }], { initialEntries: ['/before', path], initialIndex: 1 });
  render(<QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>);
  return router;
}
beforeEach(() => { jest.spyOn(console, 'info').mockImplementation(() => undefined); });
it.each(['department', 'created', 'joined'])('returns to %s through the actual detail Back button', async (tab) => {
  const router = setup();
  fireEvent.click(await screen.findByRole('radio', { name: tab }));
  fireEvent.click(await screen.findByRole('button', { name: `${tab} space` }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/knowledge/space/${tab}`));
  fireEvent.click(await screen.findByRole('button', { name: 'com_ui_go_back' }));
  expect(await screen.findByRole('region', { name: tab })).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: tab })).toBeChecked();
  expect(router.state.location.pathname).toBe('/knowledge');
});
it('retains joined through folders and both levels of Back', async () => {
  const router = setup();
  fireEvent.click(await screen.findByRole('radio', { name: 'joined' }));
  fireEvent.click(await screen.findByRole('button', { name: 'joined space' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Open folder' }));
  await waitFor(() => expect(router.state.location.pathname).toBe('/knowledge/space/joined/folder/folder-1'));
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  await waitFor(() => expect(router.state.location.pathname).toBe('/knowledge/space/joined'));
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_go_back' }));
  expect(await screen.findByRole('region', { name: 'joined' })).toBeInTheDocument();
});
it('retains joined across browser Back and Forward', async () => {
  const router = setup();
  fireEvent.click(await screen.findByRole('radio', { name: 'joined' }));
  fireEvent.click(await screen.findByRole('button', { name: 'joined space' }));
  await screen.findByRole('button', { name: 'com_ui_go_back' });
  await act(async () => { await router.navigate(-1); });
  expect(await screen.findByRole('region', { name: 'joined' })).toBeInTheDocument();
  await act(async () => { await router.navigate(1); });
  fireEvent.click(await screen.findByRole('button', { name: 'com_ui_go_back' }));
  expect(await screen.findByRole('region', { name: 'joined' })).toBeInTheDocument();
});
it.each(['joined', 'created'])('restores %s from a directly loaded detail URL', async (tab) => {
  setup(`/knowledge/space/${tab}?tab=${tab}`);
  fireEvent.click(await screen.findByRole('button', { name: 'com_ui_go_back' }));
  expect(await screen.findByRole('region', { name: tab })).toBeInTheDocument();
});
it.each(['', '?tab=unknown'])('uses the default tab for direct links with query %s', async (query) => {
  setup(`/knowledge/space/joined${query}`);
  fireEvent.click(await screen.findByRole('button', { name: 'com_ui_go_back' }));
  expect(await screen.findByRole('region', { name: 'department' })).toBeInTheDocument();
});
it('preserves other query parameters and replaces tab-only history entries', async () => {
  const router = setup('/knowledge?source=menu');
  fireEvent.click(await screen.findByRole('radio', { name: 'created' }));
  fireEvent.click(screen.getByRole('radio', { name: 'joined' }));
  expect(new URLSearchParams(router.state.location.search).get('source')).toBe('menu');
  await act(async () => { await router.navigate(-1); });
  expect(screen.getByText('Previous page')).toBeInTheDocument();
});

it('restores the requested tab after leaving the cached knowledge module', async () => {
  const router = setup('/knowledge?tab=created');
  expect(await screen.findByRole('region', { name: 'created' })).toBeInTheDocument();
  await act(async () => { await router.navigate('/before'); });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
  await act(async () => { await router.navigate('/knowledge?tab=joined'); });
  expect(await screen.findByRole('region', { name: 'joined' })).toBeInTheDocument();
});
