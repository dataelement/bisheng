// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useMoveConfirmation } from './useMoveConfirmation';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
afterEach(cleanup);

function mountConfirmation() {
  let show!: ReturnType<typeof useMoveConfirmation>['confirm'];
  function Host() {
    const { confirm, confirmationDialog } = useMoveConfirmation();
    show = confirm;
    return confirmationDialog;
  }
  return { ...render(<Host />), show: (...args: Parameters<typeof show>) => show(...args) };
}

it('settles a move confirmation once and removes the modal before execution resumes', async () => {
  const { show } = mountConfirmation();
  let result!: Promise<boolean>;
  act(() => { result = show({ title: 'Review move', description: 'Field changes', confirmText: 'Move' }); });
  expect(screen.getByRole('alertdialog').textContent).toContain('Field changes');
  fireEvent.click(screen.getByRole('button', { name: 'Move', exact: true }));
  await expect(result).resolves.toBe(true);
  expect(screen.queryByRole('alertdialog')).toBeNull();
});

it('settles both cancellation and an unmounted pending confirmation', async () => {
  const { show, unmount } = mountConfirmation();
  let cancelled!: Promise<boolean>;
  act(() => { cancelled = show({ title: 'Review move' }); });
  fireEvent.click(screen.getByRole('button', { name: 'cancel', exact: true }));
  await expect(cancelled).resolves.toBe(false);
  let retired!: Promise<boolean>;
  act(() => { retired = show({ title: 'Another move' }); });
  unmount();
  await expect(retired).resolves.toBe(false);
});
