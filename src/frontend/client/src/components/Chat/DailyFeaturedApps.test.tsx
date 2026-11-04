import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { DailyFeaturedApps } from './DailyFeaturedApps';
import { useWorkbenchNavLinks } from '~/layouts/useWorkbenchNavLinks';
import { QueryKeys } from '~/types/chat';
import { readAppChatOrigin, readAppChatReturnTo } from '~/pages/appChat/appChatOrigin';

let mockFlowType = 5;
const mockSetConversation = jest.fn();
jest.mock('~/api/apps', () => ({ getRecommendedAppsApi: async () => ({ data: [{ id: 'assistant', name: 'Recommended assistant', flow_type: mockFlowType }] }) }));
jest.mock('~/store', () => ({ __esModule: true, default: { useCreateConversationAtom: () => ({ setConversation: mockSetConversation }) } }));
jest.mock('~/utils', () => ({ cn: (...args: unknown[]) => args.filter(Boolean).join(' '), generateUUID: () => 'app-chat', addConversation: (previous: object) => ({ ...previous, added: true }) }));
jest.mock('../Avator', () => ({ __esModule: true, default: () => null }));
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: {} }),
  useLocalize: () => (key: string) => key,
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

it.each([1, 5, 10])('opens recommended app type %s without adding a daily conversation', async (flowType) => {
  mockFlowType = flowType;
  mockSetConversation.mockClear();
  sessionStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: Infinity } } });
  const dailyConversations = { pages: [{ conversations: [{ conversationId: 'daily-existing' }] }], pageParams: [] };
  client.setQueryData([QueryKeys.allConversations], dailyConversations);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/c/new']}>
    <DailyFeaturedApps t={key => key} /><Navigation />
  </MemoryRouter></QueryClientProvider>);
  fireEvent.click(await screen.findByText('Recommended assistant'));
  await waitFor(() => expect(screen.getByTestId('active-menu')).toHaveTextContent(/^apps$/));
  expect(client.getQueryData([QueryKeys.allConversations])).toEqual(dailyConversations);
  expect(mockSetConversation).not.toHaveBeenCalled();
  expect(readAppChatOrigin('app-chat')).toBe('center');
  expect(readAppChatReturnTo('app-chat')).toBe('/apps');
  expect(screen.getByTestId('address')).toHaveTextContent(`/app/app-chat/assistant/${flowType}`);
});
