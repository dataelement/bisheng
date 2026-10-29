import React, { useCallback, useState } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AliveScope } from 'react-activation';
import { createMemoryRouter, Link, Outlet, RouterProvider, useLocation, useNavigate, useParams } from 'react-router-dom';
import MainLayout from './MainLayout';
import { parkChatAsk, useChatAskHandoff } from '~/components/Chat/chatAskHandoff';
import { useConversationKnowledge } from '~/hooks/useConversationKnowledge';
const mockMobile = false;
const mockEmbedded = true;
const mockUser = { id: 'test-user', username: 'tester' };
const mockSetRecoil = jest.fn();
const mockLogout = jest.fn();
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: mockUser, logout: mockLogout, isUserLoading: false }),
  useLocalize: () => (key: string) => key,
  useWorkbenchMenuNames: () => ({ channel: 'Channel', apps: 'Apps' }),
  usePrefersMobileLayout: () => mockMobile,
  useScrollRevealRef: () => ({ current: null }),
}));
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => mockEmbedded }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
jest.mock('~/api/apps', () => ({ getBysConfigApi: async () => ({ data: {} }) }));
jest.mock('~/pages/appChat/store/atoms', () => ({ bishengConfState: 'config' }));
jest.mock('~/store', () => ({ __esModule: true, default: { mobileSystemMenuOpenState: 'mobile' } }));
jest.mock('recoil', () => ({ useRecoilState: (key: string) => jest.requireActual('react').useState(key === 'config' ? {} : false), useSetRecoilState: () => mockSetRecoil, useRecoilValue: () => false }));
jest.mock('~/components/Chat/Input/AgentToolSelector', () => ({ useAgentToolPreferences: () => {} }));
jest.mock('~/utils', () => ({ cn: (...args: unknown[]) => args.filter(Boolean).join(' ') }));
jest.mock('./DesktopShellBridge', () => ({ DesktopShellBridge: () => null }));
jest.mock('./WorkbenchAccessGuard', () => ({ __esModule: true, default: () => null }));
jest.mock('./WorkbenchSidebar', () => ({ WorkbenchSidebar: () => null }));
jest.mock('./UserPopMenu', () => ({ UserPopMenu: () => null }));
jest.mock('./useWorkbenchNavLinks', () => ({ useWorkbenchNavLinks: () => ({ links: [] }) }));
jest.mock('~/components/ui/Button', () => ({ Button: () => null }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/ui/Dialog', () => ({ Dialog: () => null, DialogContent: () => null, DialogFooter: () => null, DialogHeader: () => null, DialogTitle: () => null }));


const send = jest.fn();
function ChatPage() {
  const { conversationId = 'new' } = useParams();
  const location = useLocation();
  const [model, setModel] = useState(1);
  const { selectedOrgKbs, setSelectedOrgKbs } = useConversationKnowledge('test-user', conversationId);
  const selectModel = useCallback((id: number) => { setModel(id); return true; }, []);
  const sendMessage = useCallback((text: string) => { send({ text, conversationId, model, selectedOrgKbs }); return true; }, [conversationId, model, selectedOrgKbs]);
  useChatAskHandoff({ conversationId, activeConversationId: conversationId, locationKey: location.key,
    selectedKbs: selectedOrgKbs, setSelectedKbs: setSelectedOrgKbs, sendMessage, ready: true,
    selectedModelId: model, selectModel, onModelUnavailable: () => {} });
  return <output data-testid="chat-route" data-path={location.pathname}>{conversationId}</output>;
}
function KnowledgePage() {
  const navigate = useNavigate();
  return <button onClick={() => { parkChatAsk({ text: 'Question', modelId: 1, space: { id: '11', name: 'Space' } }); navigate('/c/new'); }}>Ask</button>;
}
function Controls() {
  return <nav><Link to="/knowledge/space/11">Knowledge</Link><Link to="/c/previous">Previous</Link></nav>;
}
class NavigationRequest {
  constructor(public url: string, public init: RequestInit) {}
  get signal() { return this.init.signal; }
  get method() { return this.init.method || 'GET'; }
}
Object.defineProperty(globalThis, 'Request', { configurable: true, value: NavigationRequest });
function open(initial: string) {
  const router = createMemoryRouter([{
    element: <><Controls /><AliveScope><Outlet /></AliveScope></>, children: [
      { element: <MainLayout />, children: [
        { path: 'c/:conversationId', element: <ChatPage /> },
        { path: 'knowledge/space/:spaceId', element: <KnowledgePage /> },
      ] },
    ],
  }], { initialEntries: [initial] });
  return render(<RouterProvider router={router} />);
}
beforeEach(() => localStorage.clear());
it('submits consecutive asks through the cached conversation route', async () => {
  open('/knowledge/space/11');
  fireEvent.click(await screen.findByRole('button', { name: 'Ask' }));
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('link', { name: 'Previous' }));
  await waitFor(() => expect(screen.getByTestId('chat-route')).toHaveTextContent('previous'));
  fireEvent.click(screen.getByRole('link', { name: 'Knowledge' }));
  await screen.findByRole('button', { name: 'Ask' });
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 1100)); });
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
  await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId('chat-route')).toHaveAttribute('data-path', '/c/new');
  expect(send.mock.calls[1][0]).toMatchObject({ conversationId: 'new', model: 1, selectedOrgKbs: [{ id: '11', name: 'Space', type: 'space' }] });
});
