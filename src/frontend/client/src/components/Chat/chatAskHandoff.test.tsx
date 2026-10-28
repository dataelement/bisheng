import { StrictMode, useCallback, useEffect, useState } from 'react';
import { act, renderHook } from '@testing-library/react';
import { parkChatAsk, useChatAskHandoff, type ChatAsk } from './chatAskHandoff';
import { useChatModelResolution, readConversationModel } from '~/hooks/useChatModelResolution';

let mockActivate: () => void;
jest.mock('react-activation', () => ({ useActivate: (callback: () => void) => { mockActivate = callback; } }));
const models = [{ id: 1, name: 'Alpha' }, { id: 2, name: 'Beta' }];
const send = jest.fn();
const rejected = jest.fn();
type Kb = { id: string; name: string; type: string };

function useLanding({ cid = 'new', ready = true, catalog = models, task = false } = {}) {
  const [mode, setMode] = useState<'daily' | 'task'>(task ? 'task' : 'daily');
  const [model, setModel] = useState({ id: 1 });
  const [kbs, setKbs] = useState<Kb[]>([{ id: 'old-space', name: 'Old', type: 'space' }]);
  const { persistPick } = useChatModelResolution({
    userId: 'tester', conversationId: cid, mode, models: catalog, adminDefaultId: '1', ready,
    onResolved: (value) => setModel({ id: Number(value.id) }),
  });
  useEffect(() => {
    if (ready) setKbs([{ id: 'saved-space', name: 'Saved', type: 'space' }]);
  }, [ready]);
  const selectModel = useCallback((id: number) => {
    if (!catalog.some((option) => option.id === id)) return false;
    persistPick(id);
    setModel({ id });
    return true;
  }, [catalog, persistPick]);
  const sendMessage = useCallback((text: string) => send({ text, model: model.id, kbs, mode }), [model, kbs, mode]);
  const onTake = useCallback(() => setMode('daily'), []);
  return useChatAskHandoff({
    conversationId: cid, locationKey: cid, selectedKbs: kbs, setSelectedKbs: setKbs,
    sendMessage, ready: ready && mode === 'daily', selectedModelId: model.id,
    selectModel, onModelUnavailable: rejected, onTake,
  });
}
const question: ChatAsk = { text: 'Count entries', modelId: 2, space: { id: 'space-1', name: 'Knowledge' } };
beforeEach(() => localStorage.clear());

test('a cached task conversation waits for the fresh daily chat and sends once with the chosen model and space', () => {
  parkChatAsk(question);
  const view = renderHook(useLanding, { initialProps: { cid: 'old-conversation', ready: false, catalog: models, task: true }, wrapper: StrictMode });
  expect(send).toHaveBeenCalledTimes(0);
  view.rerender({ cid: 'new', ready: false, catalog: models, task: true });
  act(() => mockActivate());
  expect(send).toHaveBeenCalledTimes(0);
  view.rerender({ cid: 'new', ready: true, catalog: models, task: true });
  expect(send).toHaveBeenCalledTimes(1);
  expect(send).toHaveBeenCalledWith({ text: 'Count entries', model: 2, kbs: [{ id: 'space-1', name: 'Knowledge', type: 'space' }], mode: 'daily' });
  expect(readConversationModel('tester', 'daily', 'new')).toBe('2');
  act(() => mockActivate());
  expect(send).toHaveBeenCalledTimes(1);
});

test('the same model still gets persisted for the new conversation', () => {
  parkChatAsk({ ...question, modelId: 1 });
  renderHook(useLanding);
  expect(send).toHaveBeenCalledTimes(1);
  expect(readConversationModel('tester', 'daily', 'new')).toBe('1');
});

test('an unavailable model returns the question for editing and requires a fresh pick', () => {
  parkChatAsk({ ...question, modelId: 99 });
  renderHook(useLanding);
  expect(send).toHaveBeenCalledTimes(0);
  expect(rejected).toHaveBeenCalledWith({ ...question, modelId: 99 });
});

test('an article attachment is released once after the old knowledge selection clears', () => {
  const file = new File(['Article'], 'article.md');
  parkChatAsk({ text: 'Summarize', attachment: file });
  const { result } = renderHook(useLanding);
  expect(send).toHaveBeenCalledTimes(0);
  expect(result.current.attachmentAsk).toEqual({ key: expect.any(String), text: 'Summarize', file });
  act(() => result.current.retireAttachmentAsk());
  act(() => mockActivate());
  expect(result.current.attachmentAsk).toBeNull();
});
