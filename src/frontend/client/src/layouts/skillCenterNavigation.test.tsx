import { act, fireEvent, render, screen } from '@testing-library/react';
import { AliveScope } from 'react-activation';
import { Link, MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom';
import MainLayout from './MainLayout';
import { lastSectionPaths } from './appModuleNavPaths';

let mockEnabled = true;
let mockPlugins = ['home', 'knowledge_space'];
let mockApproval = false;
const mockMenuNames = { home: 'Home', knowledge: 'Knowledge', channel: 'Subscriptions', apps: 'Apps' };
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: { plugins: mockPlugins, menu_approval_mode_workbench: mockApproval }, isUserLoading: false, logout: jest.fn() }),
  useLocalize: () => (key: string) => key,
  useWorkbenchMenuNames: () => mockMenuNames,
  usePrefersMobileLayout: () => false,
  useScrollRevealRef: () => undefined,
}));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('~/utils/platformAccess', () => ({ canOpenWorkbench: () => true, canShowPlatformAdminEntry: () => false }));
jest.mock('~/components/Skills/types', () => ({ skillCenterPath: '/c/skills', get skillCenterPreviewEnabled() { return mockEnabled; } }));
jest.mock('bisheng-icons', () => {
  const icons = new Proxy({}, { get: () => () => null });
  return { Outlined: icons, Filled: icons, Colored: icons };
});
jest.mock('~/api/apps', () => ({ getBysConfigApi: () => Promise.resolve({ data: {} }) }));
jest.mock('~/store', () => ({ __esModule: true, default: { lang: 'zh-Hans', mobileSystemMenuOpenState: false } }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: {} }));
jest.mock('recoil', () => ({ useRecoilState: (value: unknown) => jest.requireActual('react').useState(value) }));
jest.mock('./UserPopMenu', () => ({ UserPopMenu: () => null }));
jest.mock('./WorkbenchAccessGuard', () => () => null);
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/ui/Dialog', () => ({
  Dialog: () => null, DialogContent: () => null, DialogFooter: () => null,
  DialogHeader: () => null, DialogTitle: () => null,
}));

function RouteDrivenSkillDetails() {
  const [params, setParams] = useSearchParams();
  return <>
    <button onClick={() => setParams({ skill: 'platform:xlsx' })}>Open Excel details</button>
    <button onClick={() => setParams({ skill: 'platform:pptx' })}>Open PPT details</button>
    {params.get('skill') && <div role="dialog" aria-label={params.get('skill')!}>
      <button onClick={() => setParams({})}>Close details</button>
    </div>}
  </>;
}
function openRoute(path = '/c/skills') {
  render(<MemoryRouter initialEntries={[path]}><AliveScope>
    <Link to="/c/new">Go to conversation</Link><Link to="/c/skills">Return to skills</Link>
    <Routes><Route path="/" element={<MainLayout />}>
      <Route path="c/skills" element={<RouteDrivenSkillDetails />} />
      <Route path="c/new" element={<div>Conversation</div>} />
    </Route></Routes>
  </AliveScope></MemoryRouter>);
}
beforeEach(() => {
  mockEnabled = true;
  mockPlugins = ['home', 'knowledge_space'];
  mockApproval = false;
  for (const key of Object.keys(lastSectionPaths)) delete lastSectionPaths[key];
});

it('adds Skill Center to the release sidebar while preserving the last chat destination', async () => {
  lastSectionPaths.home = '/c/existing-chat';
  openRoute();
  expect(await screen.findByRole('link', { name: 'com_skill_center_title' })).toHaveAttribute('href', '/c/skills');
  expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/c/existing-chat');
});
it('keeps the entry behind the deployment flag', async () => {
  mockEnabled = false;
  openRoute('/c/new');
  await screen.findByText('Conversation');
  expect(screen.queryByRole('link', { name: 'com_skill_center_title' })).not.toBeInTheDocument();
});
it('respects the home menu permission', async () => {
  mockPlugins = ['knowledge_space'];
  openRoute('/c/new');
  await screen.findByText('Conversation');
  expect(screen.queryByRole('link', { name: 'com_skill_center_title' })).not.toBeInTheDocument();
});
it('uses the existing approval placeholder when home access is pending', async () => {
  mockPlugins = ['knowledge_space'];
  mockApproval = true;
  openRoute('/c/new');
  expect(await screen.findByRole('link', { name: 'com_skill_center_title' })).toHaveAttribute('href', '/menu-unavailable?plugin=home');
});
it('opens and closes details after returning from a frozen conversation cache', async () => {
  openRoute();
  fireEvent.click(await screen.findByRole('button', { name: 'Open Excel details' }));
  expect(await screen.findByRole('dialog', { name: 'platform:xlsx' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Close details' }));
  fireEvent.click(screen.getByRole('link', { name: 'Go to conversation' }));
  expect(await screen.findByText('Conversation')).toBeVisible();
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 1100)); });
  fireEvent.click(screen.getByRole('link', { name: 'Return to skills' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Open PPT details' }));
  expect(await screen.findByRole('dialog', { name: 'platform:pptx' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Close details' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
