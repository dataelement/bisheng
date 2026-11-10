import { hydrateStreamChatCitations } from './hydrateStreamChatCitations';
import type { ChatMessage, ChatCitation } from './chatApi';
import { transformPrivateCitations } from '@bisheng/chat/citations';

const id = 'knowledgesearch_15c85c1a';
const message = (text: string, user = false): ChatMessage => ({ text, messageId: '442820', parentMessageId: '', conversationId: 'chat', sender: 'AI', isCreatedByUser: user });
it('batches missing historical registries and retains only the sources returned by the permission service', async () => {
  const citations: ChatCitation[] = [{ citationId: id, type: 'rag', sourcePayload: { items: [{ itemId: '29' }] } }];
  const resolve = jest.fn().mockResolvedValue(citations);
  const messages = [message(`${id}:29`), message(`${id}:10 knowledgesearch_deadbeef:0`)];
  const result = await hydrateStreamChatCitations(messages, resolve);
  expect(resolve).toHaveBeenCalledTimes(1);
  expect(resolve).toHaveBeenCalledWith([id, 'knowledgesearch_deadbeef']);
  expect(result[0].citations).toEqual(citations);
  expect(result[1].citations).toEqual(citations);
  expect(result[0].text).toBe(messages[0].text);
  expect(transformPrivateCitations(result[0].text, result[0].citations).transformedContent).toBe(`[citationref:${id}:29]`);
  expect(transformPrivateCitations(result[1].text, result[1].citations).transformedContent).toBe(messages[1].text);
});
it('skips user text, code, links and already supplied registries', async () => {
  const resolve = jest.fn();
  const messages = [message(`${id}:29`, true), message(`\`${id}:29\` [link](https://example.com/${id}:29)`), { ...message(`${id}:29`), citations: [{ citationId: id, type: 'rag', itemId: '29' }] }];
  expect(await hydrateStreamChatCitations(messages, resolve)).toEqual(messages);
  expect(resolve).not.toHaveBeenCalled();
});
it('keeps history readable when registry lookup fails', async () => {
  const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
  const messages = [message(`${id}:29`)];
  expect(await hydrateStreamChatCitations(messages, jest.fn().mockRejectedValue(new Error('unavailable')))).toBe(messages);
  expect(warn).toHaveBeenCalled();
  warn.mockRestore();
});
