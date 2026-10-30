import { StrictMode, useCallback, useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';
import { act, render, renderHook } from '@testing-library/react';
import { parkChatAsk, useChatAskHandoff, type ChatAsk } from './chatAskHandoff';
import { useChatModelResolution, readConversationModel } from '~/hooks/useChatModelResolution';

let mockActivate: () => void;
jest.mock('react-activation', () => ({ useActivate: (callback: () => void) => { mockActivate = callback; } }));
const models = [{ id: 1, name: 'Alpha' }, { id: 2, name: 'Beta' }];
const send = jest.fn<boolean, [unknown]>(() => true);
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
    conversationId: cid, activeConversationId: cid, locationKey: cid, selectedKbs: kbs, setSelectedKbs: setKbs,
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

const space = { id: '101', name: 'K1' };
const selection = [{ ...space, type: 'space' }];
const strictWrapper = StrictMode;

function renderHandoff(activeConversationId = 'new') {
  const sendMessage = jest.fn(() => true);
  const onTake = jest.fn();
  const hook = renderHook(({ activeId, locationKey, send }) => {
    const [selectedKbs, setSelectedKbs] = useState(selection);
    return {
      ...useChatAskHandoff({
        conversationId: 'new', activeConversationId: activeId, locationKey,
        selectedKbs, setSelectedKbs, sendMessage: send, onTake,
        ready: true, selectedModelId: 1, selectModel: jest.fn(() => true), onModelUnavailable: rejected,
      }),
      selectedKbs,
    };
  }, { initialProps: { activeId: activeConversationId, locationKey: 'landing', send: sendMessage },
    wrapper: strictWrapper });
  return { ...hook, sendMessage, onTake };
}

test('waits for the sending conversation to reach the new route', () => {
  parkChatAsk({ text: 'question', space });
  const { rerender, sendMessage, onTake } = renderHandoff('previous-chat');
  expect(onTake).toHaveBeenCalledTimes(0);
  expect(sendMessage).toHaveBeenCalledTimes(0);
  rerender({ activeId: 'new', locationKey: 'landing', send: sendMessage });
  expect(onTake).toHaveBeenCalledTimes(1);
  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(sendMessage).toHaveBeenCalledWith('question');
});

test('keeps a rejected ask until a ready sender accepts it', () => {
  const { rerender, sendMessage } = renderHandoff();
  sendMessage.mockReturnValue(false);
  parkChatAsk({ text: 'question', space });
  act(() => mockActivate());
  expect(sendMessage).toHaveBeenCalledWith('question');
  const readySend = jest.fn(() => true);
  rerender({ activeId: 'new', locationKey: 'landing', send: readySend });
  expect(readySend).toHaveBeenCalledTimes(1);
  act(() => { mockActivate(); mockActivate(); });
  expect(readySend).toHaveBeenCalledTimes(1);
});

test('activation picks up consecutive asks with the same location and selection', () => {
  const { sendMessage } = renderHandoff();
  for (const text of ['first', 'second', 'third']) {
    parkChatAsk({ text, space });
    act(() => mockActivate());
    act(() => mockActivate());
  }
  expect(sendMessage.mock.calls).toEqual([['first'], ['second'], ['third']]);
});

test('strict effect replay submits a mounted ask exactly once', () => {
  parkChatAsk({ text: 'question', space });
  const { sendMessage } = renderHandoff();
  expect(sendMessage).toHaveBeenCalledTimes(1);
});

test('stages a plain question and retires it on acceptance', () => {
  parkChatAsk({ text: 'plain question' });
  const { sendMessage } = renderHandoff();
  expect(sendMessage).toHaveBeenCalledTimes(1);
  expect(sendMessage).toHaveBeenCalledWith('plain question');
});

test('hands consecutive article uploads to the input after the fresh chat is ready', () => {
  const file = new File(['article'], 'article.md', { type: 'text/markdown' });
  parkChatAsk({ text: 'first article question', attachment: file });
  const { result, rerender, sendMessage } = renderHandoff('previous-chat');
  expect(result.current.attachmentAsk).toBeNull();
  rerender({ activeId: 'new', locationKey: 'landing', send: sendMessage });
  const firstKey = result.current.attachmentAsk?.key;
  expect(result.current.selectedKbs).toEqual([]);
  expect(result.current.attachmentAsk?.text).toBe('first article question');
  expect(result.current.attachmentAsk?.file).toBe(file);
  act(() => result.current.retireAttachmentAsk());
  parkChatAsk({ text: 'second article question', attachment: file });
  act(() => mockActivate());
  expect(result.current.attachmentAsk?.text).toBe('second article question');
  expect(result.current.attachmentAsk?.file).toBe(file);
  expect(result.current.attachmentAsk?.key).not.toBe(firstKey);
  expect(sendMessage).toHaveBeenCalledTimes(0);
});

// Idempotent selection setters are valid: preparing an ask must advance even
// when the model and knowledge scope already match the requested values.
test.each([
  { text: 'same model and space', modelId: 1, space },
  { text: 'same space', space },
  { text: 'empty scope' },
  { text: 'article', attachment: new File(['article'], 'article.md') },
])('advances preparation with unchanged selections: $text', (ask) => {
  const sendMessage = jest.fn(() => true);
  const setSelectedKbs = jest.fn();
  const selectModel = jest.fn(() => true);
  parkChatAsk(ask);
  const { result } = renderHook(() => useChatAskHandoff({
    conversationId: 'new', activeConversationId: 'new', locationKey: 'landing',
    selectedKbs: 'space' in ask ? selection : [], setSelectedKbs, sendMessage,
    ready: true, selectedModelId: 1, selectModel, onModelUnavailable: rejected,
  }), { wrapper: StrictMode });
  if ('attachment' in ask) {
    expect(result.current.attachmentAsk).toEqual({ key: expect.any(String), text: ask.text, file: ask.attachment });
    expect(sendMessage).toHaveBeenCalledTimes(0);
  } else {
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith(ask.text);
  }
  act(() => { mockActivate(); mockActivate(); });
  expect(sendMessage).toHaveBeenCalledTimes('attachment' in ask ? 0 : 1);
});

// The production model atom notifies subscribers synchronously. The composer
// also publishes selection presence during layout, which flushes passive effects.
test.each([1, 2])('prepares once when a synchronous model store publishes model %s during layout', (modelId) => {
  let model = { id: 1 };
  const listeners = new Set<() => void>();
  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  };
  const readModel = () => model;
  const selectModel = jest.fn((id: number) => {
    model = { id };
    listeners.forEach((listener) => listener());
    return true;
  });
  const sendMessage = jest.fn<boolean, [string]>(() => true);
  const asks = [
    { text: 'first question', modelId, space: { id: '11', name: 'First space' } },
    { text: 'second question', modelId, space: { id: '12', name: 'Second space' } },
  ];
  function SelectionPresence({ selected, onChange }: { selected: boolean; onChange: (value: boolean) => void }) {
    useLayoutEffect(() => { onChange(selected); }, [selected, onChange]);
    return null;
  }
  function SynchronousLanding() {
    const selectedModel = useSyncExternalStore(subscribe, readModel);
    const [kbs, setKbs] = useState<Kb[]>([]);
    const [, setHasSelection] = useState(false);
    useChatAskHandoff({
      conversationId: 'new', activeConversationId: 'new', locationKey: 'landing',
      selectedKbs: kbs, setSelectedKbs: setKbs, selectedModelId: selectedModel.id,
      selectModel, sendMessage: (text) => {
        expect(selectedModel.id).toBe(modelId);
        expect(kbs).toEqual([{ ...asks[sendMessage.mock.calls.length].space, type: 'space' }]);
        return sendMessage(text);
      },
      ready: true, onModelUnavailable: rejected,
    });
    return <SelectionPresence selected={kbs.length > 0} onChange={setHasSelection} />;
  }
  parkChatAsk(asks[0]);
  render(<StrictMode><SynchronousLanding /></StrictMode>);
  expect(selectModel).toHaveBeenCalledTimes(1);
  expect(sendMessage).toHaveBeenCalledTimes(1);
  parkChatAsk(asks[1]);
  act(() => mockActivate());
  expect(selectModel).toHaveBeenCalledTimes(2);
  expect(sendMessage).toHaveBeenCalledTimes(2);
});
