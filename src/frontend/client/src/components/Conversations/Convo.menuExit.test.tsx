import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { TConversation } from '~/types/chat';
import Convo from './Convo';

const noop = () => undefined;
jest.mock('recoil', () => ({ useRecoilValue: (key: string) => key === 'all' ? [] : false }));
jest.mock('~/store', () => ({ __esModule: true, default: { allConversationsSelector: 'all' } }));
jest.mock('~/store/linsight', () => ({ conversationTaskRunningState: () => 'running' }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => false,
  useNavigateToConvo: () => ({ navigateWithLastTools: jest.fn() }),
}));
jest.mock('~/hooks/queries/data-provider', () => ({
  useGetEndpointsQuery: () => ({ data: undefined }),
  useUpdateConversationMutation: () => ({ mutateAsync: jest.fn() }),
}));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: noop }) }));
jest.mock('./useTitleReveal', () => ({ useTitleReveal: () => ({ ref: noop, reveal: noop, reset: noop }) }));
jest.mock('./ConvoOptions', () => ({ ConvoOptions: ({ setIsPopoverActive, onMenuExit }: { setIsPopoverActive: (value: boolean) => void; onMenuExit?: () => void }) => <>
  <button onClick={() => setIsPopoverActive(true)}>Options</button>
  <button onClick={() => setIsPopoverActive(false)}>Close options</button>
  <button onClick={onMenuExit}>Finish closing</button>
</> }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));

const conversation = { conversationId: 'one', title: 'First chat', updatedAt: '2026-10-30T00:00:00' } as TConversation;

it('keeps the menu anchor displayed until its exit animation completes', () => {
  const styles = document.createElement('style');
  styles.textContent = '.hidden { display: none; } .flex { display: flex; }';
  document.head.append(styles);
  try {
    render(<MemoryRouter initialEntries={['/c/one']}><Convo conversation={conversation} retainView={noop} toggleNav={noop} isLatestConvo={false} compact /></MemoryRouter>);
    const options = screen.getByRole('button', { name: 'Options', hidden: true });
    const slot = options.closest('.dsh-history-options') as HTMLElement;
    // The open conversation no longer pins its menu button; hover or keyboard focus reveals it.
    expect(getComputedStyle(slot).display).toBe('none');
    fireEvent.click(options);
    expect(getComputedStyle(slot).display).toBe('flex');
    fireEvent.click(screen.getByRole('button', { name: 'Close options', hidden: true }));
    // A disappearing anchor makes the still-fading floating panel jump to x=0.
    expect(getComputedStyle(slot).display).toBe('flex');
    fireEvent.click(screen.getByRole('button', { name: 'Finish closing', hidden: true }));
    expect(getComputedStyle(slot).display).toBe('none');
  } finally {
    styles.remove();
  }
});
