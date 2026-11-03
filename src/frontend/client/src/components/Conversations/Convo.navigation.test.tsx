import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { TConversation } from '~/types/chat';
import Convo from './Convo';

const mockNavigate = jest.fn();
const mockToggle = jest.fn();
let mockSmallScreen = true;
beforeEach(() => { mockSmallScreen = true; });
const noop = () => undefined;
jest.mock('recoil', () => ({ useRecoilValue: (key: string) => key === 'all' ? [] : false }));
jest.mock('~/store', () => ({ __esModule: true, default: { allConversationsSelector: 'all' } }));
jest.mock('~/store/linsight', () => ({ conversationTaskRunningState: () => 'running' }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => mockSmallScreen,
  useNavigateToConvo: () => ({ navigateWithLastTools: mockNavigate }),
}));
jest.mock('~/hooks/queries/data-provider', () => ({
  useUpdateConversationMutation: () => ({ mutate: noop }), useGetEndpointsQuery: () => ({ data: {} }),
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

it('keeps the menu anchor displayed until its exit animation completes', () => {
  mockSmallScreen = false;
  const styles = document.createElement('style');
  styles.textContent = '.hidden { display: none; } .flex { display: flex; }';
  document.head.append(styles);
  try {
    open('/c/one');
    const options = screen.getByRole('button', { name: 'Options', hidden: true });
    const slot = options.closest('.dsh-history-options') as HTMLElement;
    const row = options.closest('.dsh-history-row') as HTMLElement;
    expect(row.querySelector('time')).toBeInTheDocument();
    fireEvent.click(options);
    expect(getComputedStyle(slot).display).toBe('flex');
    expect(row.querySelector('time')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close options' }));
    // A disappearing anchor makes the still-fading floating panel jump to x=0.
    expect(getComputedStyle(slot).display).toBe('flex');
    expect(row.querySelector('time')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Finish closing' }));
    expect(getComputedStyle(slot).display).toBe('none');
    expect(row.querySelector('time')).toBeInTheDocument();
  } finally {
    styles.remove();
  }
});
