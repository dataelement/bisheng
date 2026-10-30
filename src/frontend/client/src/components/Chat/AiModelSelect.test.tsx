import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import AiModelSelect from './AiModelSelect';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
const options = [
  { id: '1', key: 'a', name: 'alpha', displayName: 'Alpha', provider_id: '10', provider_name: 'Provider A' },
  { id: '2', key: 'b', name: 'beta', displayName: 'Beta', description: 'Vision model', provider_id: '20', provider_name: 'Provider B' },
  { id: '3', key: 'c', name: 'gamma', displayName: 'Gamma', provider_id: '10', provider_name: 'Provider A' },
];

test('selects a provider then a model, commits only the model id and displays only its name', async () => {
  const change = jest.fn();
  function Picker() {
    const [value, setValue] = useState(1);
    return <AiModelSelect options={options} value={value} disabled={false} onChange={id => { change(id); setValue(Number(id)); }} />;
  }
  render(<Picker />);
  const user = userEvent.setup();
  const trigger = screen.getByRole('combobox', { name: 'com_ui_select_model' });
  expect(trigger.parentElement).toHaveTextContent('Alpha');
  expect(trigger.parentElement).not.toHaveTextContent('Provider A');
  await user.click(trigger);
  await user.click(screen.getByRole('treeitem', { name: 'Provider B' }));
  expect(change).not.toHaveBeenCalled();
  expect(screen.queryByRole('treeitem', { name: 'Gamma' })).toBeNull();
  await user.click(screen.getByRole('treeitem', { name: 'Beta' }));
  expect(change).toHaveBeenCalledWith('2');
  expect(trigger.parentElement).toHaveTextContent('Beta');
  expect(trigger.parentElement).not.toHaveTextContent('Provider B');
  await waitFor(() => expect(screen.queryByRole('tree')).toBeNull());
  expect(trigger).toHaveFocus();
});

test('searches model descriptions and lets the keyboard select the leaf', async () => {
  const change = jest.fn();
  render(<AiModelSelect options={options} value={1} disabled={false} onChange={change} />);
  const user = userEvent.setup();
  const search = screen.getByRole('combobox', { name: 'com_ui_select_model' });
  await user.click(search);
  await user.type(search, 'vision');
  const tree = await screen.findByRole('tree');
  expect(within(tree).queryByRole('treeitem', { name: 'Provider A / Alpha' })).toBeNull();
  expect(within(tree).getByRole('treeitem', { name: 'Provider B / Beta' })).toBeInTheDocument();
  await user.keyboard('{Enter}');
  expect(change).toHaveBeenCalledWith('2');
});

test('empty searches preserve selection; reopening clears search and Escape cancels', async () => {
  const change = jest.fn();
  render(<AiModelSelect options={options} value={1} disabled={false} onChange={change} />);
  const user = userEvent.setup();
  const search = screen.getByRole('combobox', { name: 'com_ui_select_model' });
  await user.click(search);
  await user.type(search, 'missing');
  expect(await screen.findByText('com_select.no_match')).toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(change).not.toHaveBeenCalled();
  await user.click(search);
  expect(search).toHaveValue('');
  expect(screen.getByRole('treeitem', { name: 'Provider A' })).toBeInTheDocument();
});

test('deduplicates model ids and keeps models without provider metadata selectable', async () => {
  const change = jest.fn();
  render(<AiModelSelect options={[
    { id: '4', key: 'd', name: 'delta', displayName: 'Delta' },
    { id: '4', key: 'd', name: 'delta', displayName: 'Duplicate' },
    { id: '', key: '', name: 'invalid', displayName: 'Invalid' },
  ]} value={4} disabled={false} onChange={change} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('combobox'));
  await user.click(screen.getByRole('treeitem', { name: 'modelPicker.unknownProvider' }));
  expect(screen.queryByText('Duplicate')).toBeNull();
  expect(screen.queryByText('Invalid')).toBeNull();
  await user.click(screen.getByRole('treeitem', { name: 'Delta' }));
  expect(change).toHaveBeenCalledWith('4');
});

test('keeps automatic repair separate from manual selection and disables opening while busy', () => {
  const repair = jest.fn(); const change = jest.fn();
  render(<AiModelSelect options={options} value={9} disabled onChange={change} onAutoChange={repair} />);
  expect(repair).toHaveBeenCalledWith('3');
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole('combobox')).toHaveAttribute('aria-disabled', 'true');
});
