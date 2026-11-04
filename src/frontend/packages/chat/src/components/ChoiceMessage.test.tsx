import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ChoiceMessage } from './ChoiceMessage';
afterEach(cleanup);
const labels = { confirm: 'Confirm', confirmed: 'Confirmed' };
it('cannot execute a historical choice, including by clicking its label', () => {
  const onSubmit = vi.fn();
  render(<ChoiceMessage kind="choice" labels={labels} canExecute={false} options={[{ id: 'one', label: 'One' }]} onSubmit={onSubmit} />);
  fireEvent.click(screen.getByText('One'));
  expect(onSubmit).not.toHaveBeenCalled();
});
it('locks an in-flight choice and permits retry after failure', async () => {
  let reject: (reason: Error) => void = () => undefined;
  const onSubmit = vi.fn().mockImplementationOnce(() => new Promise<void>((_resolve, rejectPromise) => { reject = rejectPromise; })).mockResolvedValue(undefined);
  const onError = vi.fn();
  render(<ChoiceMessage kind="choice" labels={labels} canExecute options={[{ id: 'one', label: 'One' }]} onSubmit={onSubmit} onError={onError} />);
  fireEvent.click(screen.getByText('One')); fireEvent.click(screen.getByText('One'));
  expect(onSubmit).toHaveBeenCalledTimes(1);
  reject(new Error('failed'));
  await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByText('One'));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(2));
});
it('shows the persisted input and guards empty input submission', () => {
  const onSubmit = vi.fn();
  const { rerender } = render(<ChoiceMessage kind="input" labels={labels} canExecute initialValue=" " onSubmit={onSubmit} />);
  fireEvent.click(screen.getByText('Confirm')); expect(onSubmit).not.toHaveBeenCalled();
  rerender(<ChoiceMessage kind="input" labels={labels} canExecute selectedValue="Saved" onSubmit={onSubmit} />);
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('Saved');
  fireEvent.click(screen.getByText('Confirmed')); expect(onSubmit).not.toHaveBeenCalled();
});
