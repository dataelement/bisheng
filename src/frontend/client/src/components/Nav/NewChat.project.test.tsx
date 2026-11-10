import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { useStartNewChat } from './NewChat';
import { useDesktopNavigation } from '~/components/Chat/useDesktopNavigation';
jest.mock('~/hooks/useClientEnvironment', () => ({ useClientEnvironment: () => ({ channel: 'desktop' }) }));

const mockReset = jest.fn();
jest.mock('~/hooks', () => ({ useNewConvo: () => ({ newConversation: mockReset }), useLocalize: () => (key: string) => key }));
jest.mock('recoil', () => ({ useSetRecoilState: () => jest.fn() }));
jest.mock('~/store/linsight', () => ({ taskModeState: {} }));
jest.mock('~/store', () => ({ __esModule: true, default: { useCreateConversationAtom: () => ({ conversation: { conversationId: 'existing' } }) } }));
jest.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ setQueryData: jest.fn() }) }));
jest.mock('~/types/chat', () => ({ Constants: { NEW_CONVO: 'new' }, QueryKeys: { messages: 'messages' } }));
jest.mock('../ui', () => ({ Button: () => null }));
jest.mock('bisheng-icons', () => ({ Outlined: {} }));

function setup() {
  return renderHook(() => { useDesktopNavigation(); return { start: useStartNewChat(), location: useLocation(), navigate: useNavigate() }; }, {
    wrapper: ({ children }: { children: ReactNode }) => <MemoryRouter initialEntries={['/c/existing']}>{children}</MemoryRouter>,
  });
}
beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

it('retains the selected project across both reset passes and clears it for global new chat', () => {
  const { result } = setup();
  act(() => result.current.start('project / one'));
  expect(result.current.location.search).toBe('?projectId=project%20%2F%20one');
  const draftKey = result.current.location.state.newChatKey;
  act(() => jest.advanceTimersByTime(300));
  expect(mockReset).toHaveBeenCalledTimes(2);
  expect(new URLSearchParams(result.current.location.search).get('projectId')).toBe('project / one');
  expect(result.current.location.state.newChatKey).toBe(draftKey);
  act(() => result.current.start());
  expect(result.current.location.search).toBe('');
  expect(result.current.location.state.newChatKey).not.toBe(draftKey);
});

it('mints a fresh draft identity for another explicit click on the same project', () => {
  const { result } = setup();
  act(() => result.current.start('same-project'));
  const first = result.current.location.state.newChatKey;
  act(() => result.current.start('same-project'));
  expect(result.current.location.search).toBe('?projectId=same-project');
  expect(result.current.location.state.newChatKey).not.toBe(first);
});

it('keeps the last project when another project is chosen before the second reset', () => {
  const { result } = setup();
  act(() => result.current.start('one'));
  act(() => result.current.start('two'));
  act(() => jest.advanceTimersByTime(300));
  expect(result.current.location.search).toBe('?projectId=two');
  expect(mockReset).toHaveBeenCalledTimes(3);
});

it('does not reset an existing conversation after a fast send or navigation', () => {
  const { result } = setup();
  act(() => result.current.start('one'));
  act(() => result.current.navigate('/c/created-chat'));
  act(() => jest.advanceTimersByTime(300));
  expect(result.current.location.pathname).toBe('/c/created-chat');
  expect(mockReset).toHaveBeenCalledTimes(1);
});

it('keeps the logical draft when the host restores it from settings without a reset', () => {
  const { result } = setup();
  const path = '/c/new?projectId=11111111-1111-4111-8111-111111111111';
  act(() => window.dispatchEvent(new CustomEvent('dsh:navigate', { detail: { path, resetDraft: true }, cancelable: true })));
  const key = result.current.location.state.newChatKey;
  const resets = mockReset.mock.calls.length;
  act(() => result.current.navigate('/settings/account?dshSettings=1'));
  act(() => window.dispatchEvent(new CustomEvent('dsh:navigate', { detail: { path, resetDraft: false }, cancelable: true })));
  expect(result.current.location.state.newChatKey).toBe(key);
  expect(mockReset).toHaveBeenCalledTimes(resets);
  const locationKey = result.current.location.key;
  act(() => window.dispatchEvent(new CustomEvent('dsh:navigate', { detail: { path, resetDraft: false }, cancelable: true })));
  expect(result.current.location.key).toBe(locationKey);
  act(() => window.dispatchEvent(new CustomEvent('dsh:navigate', { detail: { path, resetDraft: true }, cancelable: true })));
  expect(result.current.location.state.newChatKey).not.toBe(key);
});
