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

test('sizes the trigger from the selected label and keeps its sizing text while searching', async () => {
  const user = userEvent.setup();
  const view = render(<AiModelSelect options={options} value={1} disabled={false} onChange={jest.fn()} />);
  const input = screen.getByRole('combobox', { name: 'com_ui_select_model' });
  // The browser's default 20-character input width must not set the trigger width.
  expect(input).toHaveAttribute('size', '1');
  const sizer = input.parentElement!.querySelector('[aria-hidden="true"]');
  expect(sizer).toHaveAttribute('data-label', 'Alpha');
  view.rerender(<AiModelSelect options={options} value={3} disabled={false} onChange={jest.fn()} />);
  expect(sizer).toHaveAttribute('data-label', 'Gamma');
  await user.click(input);
  await user.type(input, 'vision');
  expect(sizer).toHaveAttribute('data-label', 'Gamma');
});

test('F016: shows the server credit ratio after model names, with the base model as a plain 1.00x', async () => {
  const priced = [
    { ...options[0], pricing_hint: { ratio: '3.00', base: false, free: false } },
    { ...options[1], pricing_hint: { ratio: '1.00', base: true, free: false } },
    { ...options[2], pricing_hint: { ratio: null, base: false, free: true } },
    { id: '4', key: 'd', name: 'delta', displayName: 'Delta', provider_id: '10', provider_name: 'Provider A', pricing_hint: { ratio: null, base: false, free: false } },
    { id: '5', key: 'e', name: 'epsilon', displayName: 'Epsilon', provider_id: '10', provider_name: 'Provider A' },
  ];
  render(<AiModelSelect options={priced} value={1} disabled={false} onChange={jest.fn()} />);
  const user = userEvent.setup();
  const trigger = screen.getByRole('combobox', { name: 'com_ui_select_model' });
  expect(trigger.parentElement).toHaveTextContent('Alpha · 3.00x');
  await user.click(trigger);
  await user.click(screen.getByRole('treeitem', { name: 'Provider A' }));
  expect(screen.getByRole('treeitem', { name: 'Gamma · modelPicker.ratioFree' })).toBeInTheDocument();
  // No ratio can be shown (unpriced base or older server): the plain name stays.
  expect(screen.getByRole('treeitem', { name: 'Delta' })).toBeInTheDocument();
  expect(screen.getByRole('treeitem', { name: 'Epsilon' })).toBeInTheDocument();
  await user.click(screen.getByRole('treeitem', { name: 'Provider B' }));
  expect(screen.getByRole('treeitem', { name: 'Beta · 1.00x' })).toBeInTheDocument();
});

// F004 design §7 item 7: the selector is off while a run is in progress.
test('a disabled selector explains itself on hover when a reason is given', async () => {
  const view = render(<AiModelSelect options={options} value={1} disabled disabledReason="after the answer" onChange={jest.fn()} />);
  const user = userEvent.setup();
  const trigger = screen.getByRole('combobox', { name: 'com_ui_select_model' });
  expect(trigger).toBeDisabled();
  expect(screen.queryByRole('tooltip')).toBeNull();
  await user.hover(trigger.closest('span[tabindex="0"]')!);
  expect(await screen.findByRole('tooltip')).toHaveTextContent('after the answer');
  // Enabled again: no hover zone is left around the selector.
  view.rerender(<AiModelSelect options={options} value={1} disabled={false} disabledReason="after the answer" onChange={jest.fn()} />);
  expect(screen.getByRole('combobox', { name: 'com_ui_select_model' }).closest('span[tabindex="0"]')).toBeNull();
  await waitFor(() => expect(screen.queryByRole('tooltip')).toBeNull());
});

test('a disabled selector without a reason gets no hover zone', () => {
  render(<AiModelSelect options={options} value={1} disabled onChange={jest.fn()} />);
  expect(screen.getByRole('combobox', { name: 'com_ui_select_model' }).closest('span[tabindex="0"]')).toBeNull();
});
