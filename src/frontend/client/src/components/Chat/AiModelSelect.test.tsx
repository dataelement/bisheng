import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AiModelSelect from './AiModelSelect';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
const options = [
  { id: '1', key: 'a', name: 'alpha', displayName: 'Alpha' },
  { id: '2', key: 'b', name: 'beta', displayName: 'Beta', description: 'Vision model' },
];

test('search filters models and keyboard selection commits the model id then restores focus', async () => {
  const change = jest.fn();
  render(<AiModelSelect options={options} value={1} disabled={false} onChange={change} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Alpha' }));
  const search = await screen.findByRole('combobox');
  await user.type(search, 'vision');
  expect(screen.queryByRole('option', { name: 'Alpha' })).toBeNull();
  await user.keyboard('{ArrowDown}{Enter}');
  await waitFor(() => expect(change).toHaveBeenCalledWith('2'));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getByRole('button', { name: 'Alpha' })).toHaveFocus();
});

test('empty searches preserve selection; reopening clears search and Escape cancels', async () => {
  const change = jest.fn();
  render(<AiModelSelect options={options} value={1} disabled={false} onChange={change} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Alpha' }));
  await user.type(await screen.findByRole('combobox'), 'missing');
  expect(screen.getByRole('status')).toHaveTextContent('com_list_no_results');
  await user.keyboard('{Escape}');
  expect(change).toHaveBeenCalledTimes(0);
  await user.click(screen.getByRole('button', { name: 'Alpha' }));
  expect(await screen.findByRole('combobox')).toHaveValue('');
  expect(screen.getAllByRole('option')).toHaveLength(2);
  fireEvent.click(screen.getByRole('option', { name: 'Beta Vision model' }));
  expect(change).toHaveBeenCalledWith('2');
});

test('keeps automatic repair separate from manual selection and disables opening while busy', () => {
  const repair = jest.fn(); const change = jest.fn();
  render(<AiModelSelect options={options} value={9} disabled onChange={change} onAutoChange={repair} />);
  expect(repair).toHaveBeenCalledWith('2');
  expect(change).toHaveBeenCalledTimes(0);
  expect(screen.getByRole('button')).toBeDisabled();
});
