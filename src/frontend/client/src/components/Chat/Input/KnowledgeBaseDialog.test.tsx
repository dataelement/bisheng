import { act, fireEvent, render, screen } from '@testing-library/react';
import { KnowledgeBaseDialog } from './KnowledgeBaseDialog';

const mockQuery = jest.fn();
const mockNext = jest.fn();
const mockRetry = jest.fn();
let mockError = false;
let mockHasMore = false;
const rows = [{ id: 1, name: 'Enterprise' }, { id: 2, name: 'Policies' }];
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/queries/data-provider', () => ({
  useGetOrgToolPages: query => {
    mockQuery(query);
    return {
      data: { pages: [{ data: rows.filter(row => row.name.toLowerCase().includes(query.name.toLowerCase())) }] },
      isFetching: false, isError: mockError, hasNextPage: mockHasMore,
      fetchNextPage: mockNext, refetch: mockRetry,
    };
  },
}));
jest.mock('@bisheng/ui', () => ({
  Modal: ({ children, title, footer, onOpenChange }) => <div role="dialog" onKeyDown={event => { if (event.key === 'Escape') onOpenChange(false); }}><h2>{title}</h2>{children}{footer}</div>,
  SearchInput: props => <input {...props} />,
  Button: ({ color, variant, ...props }) => { void color; void variant; return <button {...props} />; },
  Checkbox: ({ onCheckedChange, ...props }) => <input type="checkbox" {...props} onChange={onCheckedChange} />,
}));
const initial = [{ id: '1', name: 'Space', type: 'space' as const }, { id: '1', name: 'Enterprise', type: 'org' as const }];
beforeEach(() => { mockError = false; mockHasMore = false; });
afterEach(() => { jest.useRealTimers(); });

test('keeps selections across server searches and applies only on confirmation, preserving spaces', () => {
  jest.useFakeTimers();
  const confirm = jest.fn();
  const close = jest.fn();
  render(<KnowledgeBaseDialog value={initial} onConfirm={confirm} onClose={close} />);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Policies' }));
  expect(confirm).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Enterprise' } });
  act(() => { jest.advanceTimersByTime(500); });
  expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ name: 'Enterprise', action: 'visible', page_size: 20 }));
  expect(screen.queryByRole('checkbox', { name: 'Policies' })).toBeNull();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enterprise' }));
  fireEvent.click(screen.getByText('dshChat.confirmKnowledge'));
  expect(confirm).toHaveBeenCalledWith([initial[0], { id: '2', name: 'Policies', type: 'org' }]);
  expect(close).toHaveBeenCalledTimes(1);
});

test.each(['cancel', 'escape'])('%s discards the knowledge-base draft', exit => {
  const confirm = jest.fn();
  const close = jest.fn();
  render(<KnowledgeBaseDialog value={initial} onConfirm={confirm} onClose={close} />);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Policies' }));
  if (exit === 'cancel') fireEvent.click(screen.getByText('com_ui_cancel'));
  else fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(confirm).not.toHaveBeenCalled();
  expect(close).toHaveBeenCalledTimes(1);
});

test('pins admin-configured libraries in configured sort order', () => {
  render(<KnowledgeBaseDialog value={[]} onConfirm={jest.fn()} onClose={jest.fn()}
    configured={[{ id: 1, name: 'Enterprise', sort_order: 2 }, { id: 2, name: 'Policies', sort_order: 1 }]} />);
  expect(screen.getAllByRole('checkbox').map(node => node.getAttribute('aria-label'))).toEqual(['Policies', 'Enterprise']);
  expect(mockQuery).toHaveBeenCalledWith(expect.objectContaining({ preferred_ids: '1,2', sort_by: 'name' }));
});

test('loads the next cursor page when scrolled to the end', () => {
  mockHasMore = true;
  render(<KnowledgeBaseDialog value={[]} onConfirm={jest.fn()} onClose={jest.fn()} />);
  const list = document.querySelector('.dsh-knowledge-list')!;
  Object.defineProperties(list, { scrollHeight: { value: 200 }, clientHeight: { value: 100 }, scrollTop: { value: 100 } });
  fireEvent.scroll(list);
  expect(mockNext).toHaveBeenCalledTimes(1);
});

test('failed reads disable confirmation and offer retry', () => {
  mockError = true;
  render(<KnowledgeBaseDialog value={initial} onConfirm={jest.fn()} onClose={jest.fn()} />);
  expect(screen.getByRole('alert')).toHaveTextContent('knowledgeBasePicker.loadError');
  expect(screen.getByText('dshChat.confirmKnowledge')).toBeDisabled();
  fireEvent.click(screen.getByText('dshChat.retryKnowledge'));
  expect(mockRetry).toHaveBeenCalledTimes(1);
});

test('limits library selection to 50 while permitting existing choices to be removed', () => {
  const selected = Array.from({ length: 50 }, (_, index) => ({ id: String(index + 1), name: String(index), type: 'org' as const }));
  selected[1].id = '999';
  render(<KnowledgeBaseDialog value={selected} onConfirm={jest.fn()} onClose={jest.fn()} />);
  expect(screen.getByRole('checkbox', { name: 'Policies' })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: 'Enterprise' })).not.toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Enterprise' }));
  expect(screen.getByRole('checkbox', { name: 'Policies' })).not.toBeDisabled();
});
