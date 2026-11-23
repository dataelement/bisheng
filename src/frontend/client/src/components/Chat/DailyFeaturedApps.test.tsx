import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { DailyFeaturedApps } from './DailyFeaturedApps';
import { getRecommendedAppsApi } from '~/api/apps';
import { useWorkbenchNavLinks } from '~/layouts/useWorkbenchNavLinks';
import { QueryKeys } from '~/types/chat';
import { readAppChatOrigin, readAppChatReturnTo } from '~/pages/appChat/appChatOrigin';

let mockFlowType = 5;
let mockLegacyFormat = false;
const mockSetConversation = jest.fn();
const mockCheckResourceAction = jest.fn();
jest.mock('~/api/apps', () => ({ getRecommendedAppsApi: jest.fn(async () => ({
  data: [{ id: 'assistant', name: 'Recommended assistant', ...(mockLegacyFormat
    ? { type: mockFlowType, tags: ['Legacy tag'] }
    : { flow_type: mockFlowType, can_share: true }) }],
})) }));
jest.mock('~/api/permission', () => ({ checkResourceAction: (...args: unknown[]) => mockCheckResourceAction(...args) }));
jest.mock('~/store', () => ({ __esModule: true, default: { useCreateConversationAtom: () => ({ setConversation: mockSetConversation }) } }));
jest.mock('~/utils', () => ({ cn: (...args: unknown[]) => args.filter(Boolean).join(' '), generateUUID: () => 'app-chat', addConversation: (previous: object) => ({ ...previous, added: true }) }));
jest.mock('~/components/Avator', () => ({ __esModule: true, default: () => null }));
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: {} }),
  useLocalize: () => (key: string) => key,
  useMediaQuery: (query: string) => query === '(hover: hover) and (pointer: fine)',
  useWorkbenchMenuNames: () => ({ home: 'Home', apps: 'Apps' }),
  usePrefersMobileLayout: () => false,
}));
jest.mock('~/utils/platformAccess', () => ({ canOpenWorkbench: () => true, canShowPlatformAdminEntry: () => false }));

function Navigation() {
  const location = useLocation();
  const { links } = useWorkbenchNavLinks();
  return <><output data-testid="address">{location.pathname}{location.search}</output>
    <output data-testid="active-menu">{links.filter(link => link.isActive).map(link => link.section).join(',')}</output></>;
}

it('hides cached cards when the workspace config clears recommendations and reloads on a new selection', async () => {
  const request = jest.mocked(getRecommendedAppsApi);
  request.mockClear();
  request.mockResolvedValueOnce({ data: [{ id: 'assistant', name: 'Original app', flow_type: 5 }] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: Infinity } } });
  const page = (configuredAppIds: string[]) => (
    <QueryClientProvider client={client}><MemoryRouter>
      <DailyFeaturedApps t={key => key} configuredAppIds={configuredAppIds} />
    </MemoryRouter></QueryClientProvider>
  );
  const view = render(page(['assistant']));
  expect(await screen.findByText('Original app')).toBeInTheDocument();

  view.rerender(page([]));
  expect(screen.queryByText('Original app')).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'dshChat.recommendedApps' })).not.toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(1);

  request.mockResolvedValueOnce({ data: [{ id: 'workflow', name: 'Replacement app', flow_type: 10 }] });
  view.rerender(page(['workflow']));
  expect(await screen.findByText('Replacement app')).toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(2);
});

it.each([[1, false], [5, false], [10, false], [10, true]] as const)(
  'opens recommended app type %s without adding a daily conversation (legacy: %s)', async (flowType, legacy) => {
  mockFlowType = flowType;
  mockLegacyFormat = legacy;
  mockSetConversation.mockClear();
  mockCheckResourceAction.mockClear();
  sessionStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: Infinity } } });
  const dailyConversations = { pages: [{ conversations: [{ conversationId: 'daily-existing' }] }], pageParams: [] };
  client.setQueryData([QueryKeys.allConversations], dailyConversations);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/c/new']}>
    <DailyFeaturedApps t={key => key} /><Navigation />
  </MemoryRouter></QueryClientProvider>);
  const cardTitle = await screen.findByText('Recommended assistant');
  fireEvent.mouseEnter(cardTitle);
  expect(screen.queryByRole('button', { name: 'com_app_share_app' })).not.toBeInTheDocument();
  expect(mockCheckResourceAction).not.toHaveBeenCalled();
  fireEvent.click(cardTitle);
  await waitFor(() => expect(screen.getByTestId('active-menu')).toHaveTextContent(/^apps$/));
  expect(client.getQueryData([QueryKeys.allConversations])).toEqual(dailyConversations);
  expect(mockSetConversation).not.toHaveBeenCalled();
  expect(readAppChatOrigin('app-chat')).toBe('center');
  expect(readAppChatReturnTo('app-chat')).toBe('/apps');
  expect(screen.getByTestId('address')).toHaveTextContent(`/app/app-chat/assistant/${flowType}`);
});
