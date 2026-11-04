import { act, renderHook } from '@testing-library/react';
import { useConversationKnowledge } from './useConversationKnowledge';

const k1 = [{ id: '101', name: 'K1', type: 'space' }];
const k2 = [{ id: '202', name: 'K2', type: 'space' }];
const org = [{ id: '303', name: 'Organization', type: 'org' }];
beforeEach(() => localStorage.clear());

it('isolates accounts and restores saved selections across remounts', () => {
  const { result, rerender, unmount } = renderHook(({ user }) => useConversationKnowledge(user, 'c1'), {
    initialProps: { user: 'u1' },
  });
  act(() => result.current.setSelectedOrgKbs(k1));
  rerender({ user: 'u2' });
  expect(result.current.selectedOrgKbs).toEqual([]);
  act(() => result.current.setSelectedOrgKbs(k2));
  rerender({ user: 'u1' });
  expect(result.current.selectedOrgKbs).toEqual(k1);
  unmount();
  expect(renderHook(() => useConversationKnowledge('u2', 'c1')).result.current.selectedOrgKbs).toEqual(k2);
});

it('applies defaults to new chats and preserves explicit clears', () => {
  const chat = renderHook(({ cid }) => useConversationKnowledge('u1', cid, org), {
    initialProps: { cid: 'new' },
  });
  expect(chat.result.current.selectedOrgKbs).toEqual(org);
  act(() => chat.result.current.setSelectedOrgKbs([]));
  chat.rerender({ cid: 'c1' });
  expect(chat.result.current.selectedOrgKbs).toEqual([]);
  chat.rerender({ cid: 'new' });
  expect(chat.result.current.selectedOrgKbs).toEqual([]);
});

it('keeps a newer draft when a previous first turn receives its server id', () => {
  const chat = renderHook(() => useConversationKnowledge('u1', 'new'));
  act(() => chat.result.current.setSelectedOrgKbs(k1));
  const snapshot = chat.result.current.selectedOrgKbs;
  act(() => chat.result.current.setSelectedOrgKbs(k2));
  act(() => chat.result.current.promoteSelection('new', 'c1', snapshot));
  expect(chat.result.current.selectedOrgKbs).toEqual(k2);
  expect(renderHook(() => useConversationKnowledge('u1', 'c1')).result.current.selectedOrgKbs).toEqual(k1);
});

it('binds retained callbacks to their original conversation', () => {
  const chat = renderHook(({ cid }) => useConversationKnowledge('u1', cid), { initialProps: { cid: 'c1' } });
  const updateC1 = chat.result.current.setSelectedOrgKbs;
  chat.rerender({ cid: 'c2' });
  act(() => chat.result.current.setSelectedOrgKbs(k2));
  act(() => updateC1(k1));
  expect(chat.result.current.selectedOrgKbs).toEqual(k2);
  chat.rerender({ cid: 'c1' });
  expect(chat.result.current.selectedOrgKbs).toEqual(k1);
});

it('keeps main-chat and subscription drafts separate', () => {
  const main = renderHook(() => useConversationKnowledge('u1', 'new'));
  act(() => main.result.current.setSelectedOrgKbs(k1));
  const dock = renderHook(() => useConversationKnowledge('u1', 'new', [], true, 'subscription'));
  expect(dock.result.current.selectedOrgKbs).toEqual([]);
  act(() => dock.result.current.setSelectedOrgKbs(k2));
  expect(main.result.current.selectedOrgKbs).toEqual(k1);
});

it('keeps knowledge spaces when organization knowledge is disabled', () => {
  const chat = renderHook(({ enabled }) => useConversationKnowledge('u1', 'c1', [], enabled), {
    initialProps: { enabled: true },
  });
  act(() => chat.result.current.setSelectedOrgKbs([...org, ...k1]));
  chat.rerender({ enabled: false });
  expect(chat.result.current.selectedOrgKbs).toEqual(k1);
});

it('retains mounted selections when persistent storage is unavailable', () => {
  jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
  const chat = renderHook(({ cid }) => useConversationKnowledge('u1', cid), { initialProps: { cid: 'c1' } });
  act(() => chat.result.current.setSelectedOrgKbs(k1));
  chat.rerender({ cid: 'c2' });
  act(() => chat.result.current.setSelectedOrgKbs(k2));
  chat.rerender({ cid: 'c1' });
  expect(chat.result.current.selectedOrgKbs).toEqual(k1);
});
