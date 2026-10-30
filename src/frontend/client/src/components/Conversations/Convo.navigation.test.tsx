import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { TConversation } from '~/types/chat';
import Convo from './Convo';

const mockNavigate = jest.fn();
const mockToggle = jest.fn();
const noop = () => undefined;
jest.mock('recoil', () => ({ useRecoilValue: (key: string) => key === 'all' ? [] : false }));
jest.mock('~/store', () => ({ __esModule: true, default: { allConversationsSelector: 'all' } }));
jest.mock('~/store/linsight', () => ({ conversationTaskRunningState: () => 'running' }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => true,
  useNavigateToConvo: () => ({ navigateWithLastTools: mockNavigate }),
}));
jest.mock('~/hooks/queries/data-provider', () => ({
  useUpdateConversationMutation: () => ({ mutate: noop }), useGetEndpointsQuery: () => ({ data: {} }),
}));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: noop }) }));
jest.mock('./useTitleReveal', () => ({ useTitleReveal: () => ({ ref: noop, reveal: noop, reset: noop }) }));
jest.mock('./ConvoOptions', () => ({ ConvoOptions: ({ setIsPopoverActive }: { setIsPopoverActive: (value: boolean) => void }) => <button onClick={() => setIsPopoverActive(true)}>Options</button> }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));

const conversation = { conversationId: 'one', title: 'First chat', updatedAt: '2026-10-30T00:00:00' } as TConversation;
function open(path: string) {
  render(<MemoryRouter initialEntries={[path]}><Convo conversation={conversation} retainView={noop} toggleNav={mockToggle} isLatestConvo={false} compact /></MemoryRouter>);
}

it.each(['/c/one', '/linsight/one', '/app/one/flow/5'])('closes navigation without navigating again from %s', (path) => {
  open(path);
  fireEvent.click(screen.getByRole('link', { name: 'First chat' }));
  expect(mockToggle).toHaveBeenCalledTimes(1);
  expect(mockNavigate).not.toHaveBeenCalled();
});

it('closes navigation and opens a different conversation', () => {
  open('/c/other');
  fireEvent.click(screen.getByRole('link', { name: 'First chat' }));
  expect(mockToggle).toHaveBeenCalledTimes(1);
  expect(mockNavigate).toHaveBeenCalledWith(conversation, false);
});

it('does not close navigation while the row owns its options menu', () => {
  open('/c/other');
  fireEvent.click(screen.getByRole('button', { name: 'Options' }));
  fireEvent.click(screen.getByRole('link', { name: 'First chat' }));
  expect(mockToggle).not.toHaveBeenCalled();
  expect(mockNavigate).not.toHaveBeenCalled();
});
