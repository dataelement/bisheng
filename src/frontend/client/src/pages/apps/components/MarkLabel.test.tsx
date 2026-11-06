import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode, type ReactNode } from 'react';
import { getAllLabelsApi, updateHomeLabelApi } from '~/api/apps';
import MarkLabel from './MarkLabel';

jest.mock('~/api/apps', () => ({ getAllLabelsApi: jest.fn(), updateHomeLabelApi: jest.fn() }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.join(' ') }));
jest.mock('~/components', () => {
  const Container = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    Dialog: Container, DialogContent: Container, DialogFooter: Container,
    DialogHeader: Container, DialogTitle: Container,
    Button: ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => <button onClick={onClick}>{children}</button>,
  };
});

const home = [{ label: 'Category One', value: 1 }, { label: 'Category Two', value: 2 }];
const selector = '[data-rfd-draggable-id], [data-rbd-draggable-id]';

beforeEach(() => {
  jest.mocked(getAllLabelsApi).mockResolvedValue({ data: { data: [{ id: 1, name: 'Category One' }, { id: 2, name: 'Category Two' }] } });
  jest.mocked(updateHomeLabelApi).mockResolvedValue(undefined);
  jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const index = [...document.querySelectorAll(selector)].indexOf(this);
    return {
      x: 0, y: Math.max(0, index) * 48, top: Math.max(0, index) * 48,
      left: 0, right: 400, bottom: index < 0 ? 400 : index * 48 + 40,
      width: 400, height: index < 0 ? 400 : 40, toJSON: () => ({}),
    };
  });
});
afterEach(() => { cleanup(); jest.restoreAllMocks(); });

async function drag(cancel = false) {
  await waitFor(() => expect(document.querySelectorAll(selector)).toHaveLength(2));
  let item = document.querySelector<HTMLElement>(selector)!;
  const id = item.getAttribute('data-rfd-draggable-id') || item.getAttribute('data-rbd-draggable-id');
  item.focus();
  fireEvent.keyDown(item, { key: ' ', code: 'Space', keyCode: 32 });
  await waitFor(() => expect(document.body.textContent).toContain('You have lifted an item'));
  // Dragging portals the row into body; dispatch subsequent keys on its new node.
  item = document.querySelector<HTMLElement>(`[data-rfd-draggable-id="${id}"], [data-rbd-draggable-id="${id}"]`)!;
  item.focus();
  fireEvent.keyDown(item, { key: 'ArrowDown', code: 'ArrowDown', keyCode: 40 });
  await waitFor(() => expect(document.body.textContent).toContain('to position 2'));
  fireEvent.keyDown(item, cancel ? { key: 'Escape', keyCode: 27 } : { key: ' ', keyCode: 32 });
  const event = new Event('transitionend', { bubbles: true });
  Object.defineProperty(event, 'propertyName', { value: 'transform' });
  fireEvent(item, event);
  await waitFor(() => expect(document.body.textContent).toContain(cancel ? 'The item has returned' : 'You have dropped the item'));
}

it('saves category IDs in the reordered display order only on explicit confirmation', async () => {
  const onClose = jest.fn();
  render(<StrictMode><MarkLabel open home={home} onClose={onClose} /></StrictMode>);
  await drag();
  expect(updateHomeLabelApi).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'com_label_save' }));
  await waitFor(() => expect(onClose).toHaveBeenCalledWith(true));
  expect(updateHomeLabelApi).toHaveBeenCalledTimes(1);
  expect(updateHomeLabelApi).toHaveBeenCalledWith([2, 1]);
});

it('does not persist category order after drag cancellation and closing the dialog', async () => {
  const onClose = jest.fn();
  render(<StrictMode><MarkLabel open home={home} onClose={onClose} /></StrictMode>);
  await drag(true);
  fireEvent.click(screen.getByRole('button', { name: 'com_label_cancel' }));
  expect(onClose).toHaveBeenCalledWith(false);
  expect(updateHomeLabelApi).not.toHaveBeenCalled();
});
