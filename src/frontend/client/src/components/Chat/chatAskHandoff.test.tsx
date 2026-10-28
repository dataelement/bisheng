import { StrictMode, useState } from 'react';
import type { PropsWithChildren } from 'react';
import { act, renderHook } from '@testing-library/react';
import { parkChatAsk, useChatAskHandoff } from './chatAskHandoff';

let mockActivate: () => void;
jest.mock('react-activation', () => ({
  useActivate: (callback: () => void) => { mockActivate = callback; },
}));

const space = { id: '101', name: 'K1' };
const selection = [{ ...space, type: 'space' }];
const strictWrapper = ({ children }: PropsWithChildren) => <StrictMode>{children}</StrictMode>;

function renderHandoff(activeConversationId = 'new') {
  const sendMessage = jest.fn(() => true);
  const onTake = jest.fn();
  const hook = renderHook(({ activeId, locationKey, send }) => {
    const [selectedKbs, setSelectedKbs] = useState(selection);
    return {
      ...useChatAskHandoff({
        conversationId: 'new', activeConversationId: activeId, locationKey,
        selectedKbs, setSelectedKbs, sendMessage: send, onTake,
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
