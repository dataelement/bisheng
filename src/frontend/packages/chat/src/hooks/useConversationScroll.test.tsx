import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useRef } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { useConversationScroll } from './useConversationScroll';
afterEach(cleanup);
function Fixture({ ids, session = 'a', load = () => undefined, rowHeight = 500 }: { ids: string[]; session?: string; load?: () => void | Promise<unknown>; rowHeight?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useConversationScroll({ scrollRef: ref, messages: ids.map(key => ({ key })), sessionKey: session, canLoadOlder: true, onLoadOlder: load });
  return <div data-testid="viewport" ref={node => {
    Object.defineProperty(ref, 'current', { value: node, writable: true });
    if (node) {
      Object.defineProperty(node, 'scrollHeight', { configurable: true, get: () => Number(node.dataset.count) * Number(node.dataset.rowHeight) });
      Object.defineProperty(node, 'clientHeight', { configurable: true, value: 300 });
    }
  }} data-count={ids.length} data-row-height={rowHeight} />;
}
it('keeps a reader in place and anchors prepended history before following the next session', () => {
  const { rerender } = render(<Fixture ids={['1', '2']} />);
  const node = screen.getByTestId('viewport'); node.scrollTop = 100; fireEvent.scroll(node);
  rerender(<Fixture ids={['1', '2', '3']} />); expect(node.scrollTop).toBe(100);
  rerender(<Fixture ids={['0', '1', '2', '3']} />); expect(node.scrollTop).toBe(600);
  rerender(<Fixture ids={['b1']} session="b" />); expect(node.scrollTop).toBe(500);
});
it('runs one older-history request while the first is pending', async () => {
  const load = vi.fn().mockReturnValue(new Promise(() => undefined));
  render(<Fixture ids={['1', '2']} load={load} />);
  const node = screen.getByTestId('viewport'); node.scrollTop = 0;
  fireEvent.scroll(node); fireEvent.scroll(node);
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
});

it('fills an underfilled viewport once per new history cursor without a retry loop', async () => {
  const load = vi.fn().mockResolvedValue(undefined);
  const { rerender } = render(<Fixture ids={['1']} rowHeight={50} load={load} />);
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  await act(async () => { rerender(<Fixture ids={['1']} rowHeight={50} load={load} />); });
  expect(load).toHaveBeenCalledTimes(1);
  rerender(<Fixture ids={['0', '1']} rowHeight={50} load={load} />);
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
});
