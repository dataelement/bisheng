import { fireEvent, render, screen } from '@testing-library/react';
import { CurrentAppVisibility } from './CurrentAppVisibility';
import type { LocalizeFn } from './approvalPresentation';
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
const localize: LocalizeFn = key => String(key);

it('shows current typed subjects and never turns unavailable scope into owner-only', () => {
  const refresh = jest.fn();
  const view = render(<CurrentAppVisibility localize={localize} onRefresh={refresh} value={{ state: 'available', owner_only: false, subjects: [
    { type: 'department', id: '12', name: 'Research', userset_relation: 'member', include_children: true },
    { type: 'user_group', id: '12', name: 'Developers', userset_relation: 'admin' },
  ] }} />);
  expect(screen.getByText(/Research/)).toBeInTheDocument();
  expect(screen.getByText(/Developers/)).toBeInTheDocument();
  expect(screen.getByText(/approval.current_visibility.children/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'approval.current_visibility.refresh' }));
  expect(refresh).toHaveBeenCalledTimes(1);
  view.rerender(<CurrentAppVisibility localize={localize} value={{ state: 'unavailable', subjects: [], owner_only: null }} />);
  expect(screen.getByText('approval.current_visibility.unavailable')).toBeInTheDocument();
  expect(screen.queryByText('approval.current_visibility.ownerOnly')).not.toBeInTheDocument();
});

it.each(['unavailable', 'deleted', undefined] as const)('renders an explicit state for %s', state => {
  render(<CurrentAppVisibility localize={localize} value={state ? { state, subjects: [] } : undefined} />);
  expect(screen.queryByText('approval.current_visibility.ownerOnly')).not.toBeInTheDocument();
  expect(screen.getByText(`approval.current_visibility.${state === 'deleted' ? 'deleted' : 'unavailable'}`)).toBeInTheDocument();
});
