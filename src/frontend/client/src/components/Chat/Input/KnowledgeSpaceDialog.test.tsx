import { fireEvent, render, screen } from '@testing-library/react';
import { KnowledgeSpaceDialog } from './KnowledgeSpaceDialog';

const spaces = [{ id: '1', name: 'Policy' }, { id: '2', name: 'Product' }];
let mockError = false;
const mockRetry = jest.fn();
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => key,
  useCategorizedKnowledgeSpaces: ({ keyword }) => ({
    groups: [{ key: 'created', label: 'Mine', spaces: spaces.filter((item) => item.name.toLowerCase().includes(keyword.toLowerCase())) }],
    isFetching: false, isError: mockError, retry: mockRetry,
  }),
}));
jest.mock('@bisheng/ui', () => ({
  Modal: ({ children, footer, onOpenChange }) => <div role="dialog" onKeyDown={(event) => { if (event.key === 'Escape') onOpenChange(false); }}>{children}{footer}</div>,
  SearchInput: (props) => <input {...props} />,
  Button: ({ color, variant, ...props }) => { void color; void variant; return <button {...props} />; },
  Checkbox: ({ onCheckedChange, ...props }) => <input type="checkbox" {...props} onChange={onCheckedChange} />,
}));
const original = [{ id: 'org', name: 'Enterprise', type: 'org' as const }, { id: '1', name: 'Policy', type: 'space' as const }];
beforeEach(() => { mockError = false; mockRetry.mockClear(); });

test('selection is a draft across search and commits once, preserving organization knowledge', () => {
  const onConfirm = jest.fn(); const onClose = jest.fn();
  render(<KnowledgeSpaceDialog value={original} onConfirm={onConfirm} onClose={onClose} />);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Product' }));
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Policy' } });
  expect(screen.queryByRole('checkbox', { name: 'Product' })).toBeNull();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Policy' }));
  fireEvent.click(screen.getByText('dshChat.confirmKnowledge'));
  expect(onConfirm).toHaveBeenCalledWith([original[0], { id: '2', name: 'Product', type: 'space' }]);
  expect(onClose).toHaveBeenCalledTimes(1);
});

test.each(['cancel', 'escape'])('%s discards pending changes', (exit) => {
  const onConfirm = jest.fn(); const onClose = jest.fn();
  render(<KnowledgeSpaceDialog value={original} onConfirm={onConfirm} onClose={onClose} />);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Product' }));
  if (exit === 'cancel') fireEvent.click(screen.getByText('com_ui_cancel'));
  else fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(onConfirm).not.toHaveBeenCalled(); expect(onClose).toHaveBeenCalledTimes(1);
});

test('loading failures offer retry and prevent applying an incomplete result', () => {
  mockError = true;
  render(<KnowledgeSpaceDialog value={original} onConfirm={jest.fn()} onClose={jest.fn()} />);
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.getByText('dshChat.confirmKnowledge')).toBeDisabled();
  fireEvent.click(screen.getByText('dshChat.retryKnowledge'));
  expect(mockRetry).toHaveBeenCalledTimes(1);
});

test('selection limit prevents adding more spaces', () => {
  const value = Array.from({ length: 50 }, (_, index) => ({ id: String(index + 3), name: String(index), type: 'space' as const }));
  render(<KnowledgeSpaceDialog value={value} onConfirm={jest.fn()} onClose={jest.fn()} />);
  expect(screen.getByRole('checkbox', { name: 'Product' })).toBeDisabled();
});
