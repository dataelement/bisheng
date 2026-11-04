import { act, renderHook } from '@testing-library/react';
import { useKnowledgeHomeSort } from './useKnowledgeHomeSort';

let mockUser: { id: string } | undefined;
jest.mock('~/hooks', () => ({ useAuthContext: () => ({ user: mockUser }) }));

beforeEach(() => {
  window.localStorage.clear();
  mockUser = { id: 'alice' };
});

it('uses creation time until a preference exists without writing a default snapshot', () => {
  const { result } = renderHook(() => useKnowledgeHomeSort());
  expect(result.current[0]).toBe('create_time');
  expect(window.localStorage.length).toBe(0);
});

it.each(['name', 'update_time', 'create_time'] as const)('persists %s immediately and restores it on a fresh mount', (sort) => {
  const first = renderHook(() => useKnowledgeHomeSort());
  act(() => first.result.current[1](sort));
  expect(window.localStorage.getItem('knowledge-home-sort:alice')).toBe(sort);
  first.unmount();

  const next = renderHook(() => useKnowledgeHomeSort());
  expect(next.result.current[0]).toBe(sort);
});

it.each(['unsupported', 'null', '{broken'])('ignores an invalid stored value: %s', (saved) => {
  window.localStorage.setItem('knowledge-home-sort:alice', saved);
  const { result } = renderHook(() => useKnowledgeHomeSort());
  expect(result.current[0]).toBe('create_time');
});

it('restores each account without overwriting the next account with the previous selection', () => {
  window.localStorage.setItem('knowledge-home-sort:alice', 'name');
  window.localStorage.setItem('knowledge-home-sort:bob', 'update_time');
  const { result, rerender } = renderHook(() => useKnowledgeHomeSort());
  expect(result.current[0]).toBe('name');

  mockUser = { id: 'bob' };
  rerender();
  expect(result.current[0]).toBe('update_time');
  expect(window.localStorage.getItem('knowledge-home-sort:bob')).toBe('update_time');
  act(() => result.current[1]('create_time'));

  mockUser = { id: 'alice' };
  rerender();
  expect(result.current[0]).toBe('name');
  expect(window.localStorage.getItem('knowledge-home-sort:alice')).toBe('name');
  expect(window.localStorage.getItem('knowledge-home-sort:bob')).toBe('create_time');
});

it('waits for account identity before restoring or saving a preference', () => {
  window.localStorage.setItem('knowledge-home-sort:alice', 'update_time');
  mockUser = undefined;
  const { result, rerender } = renderHook(() => useKnowledgeHomeSort());
  act(() => result.current[1]('name'));
  expect(window.localStorage.length).toBe(1);

  mockUser = { id: 'alice' };
  rerender();
  expect(result.current[0]).toBe('update_time');
});

it('keeps sorting usable if browser storage cannot be read or written', () => {
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Storage blocked'); });
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage blocked'); });
  const { result } = renderHook(() => useKnowledgeHomeSort());
  expect(result.current[0]).toBe('create_time');
  act(() => result.current[1]('name'));
  expect(result.current[0]).toBe('name');
});
