import { fireEvent, waitFor } from '@testing-library/react';
import { expect, vi } from 'vitest';

const itemSelector = '[data-rfd-draggable-id], [data-rbd-draggable-id]';

export function installDragDimensions() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    const items = [...document.querySelectorAll<HTMLElement>(itemSelector)];
    const index = items.indexOf(this);
    return {
      x: 0, y: Math.max(0, index) * 48,
      top: Math.max(0, index) * 48, left: 0, right: 400,
      bottom: index < 0 ? 400 : index * 48 + 40,
      width: 400, height: index < 0 ? 400 : 40,
      toJSON: () => ({}),
    };
  });
}

export async function keyboardDrag(from = 0, cancel = false, move = true) {
  const item = document.querySelectorAll<HTMLElement>(itemSelector)[from];
  const handle = item.matches('[role="button"]') ? item : item.querySelector<HTMLElement>('[role="button"]');
  expect(handle).not.toBeNull();
  handle!.focus();
  fireEvent.keyDown(handle!, { key: ' ', code: 'Space', keyCode: 32 });
  await waitFor(() => expect(document.body.textContent).toContain('You have lifted an item'));
  if (move) {
    fireEvent.keyDown(handle!, { key: 'ArrowDown', code: 'ArrowDown', keyCode: 40 });
    await waitFor(() => expect(document.body.textContent).toContain(`to position ${from + 2}`));
  }
  fireEvent.keyDown(handle!, cancel
    ? { key: 'Escape', code: 'Escape', keyCode: 27 }
    : { key: ' ', code: 'Space', keyCode: 32 });
  const transitionEnd = new Event('transitionend', { bubbles: true });
  Object.defineProperty(transitionEnd, 'propertyName', { value: 'transform' });
  fireEvent(item, transitionEnd);
  await waitFor(() => expect(document.body.textContent).toContain(cancel ? 'The item has returned' : 'You have dropped the item'));
}
