import request from './request';
import { getChannelChatHistory, getFileChatHistory, getFolderChatHistory } from './chatApi';
import { transformPrivateCitations } from '@bisheng/chat/citations';
jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn(), post: jest.fn() } }));

it.each([
  { name: 'file', id: 'knowledgesearch_a1', load: () => getFileChatHistory('4064', '97428'), oldestFirst: false },
  { name: 'folder', id: 'knowledgesearch_a2', load: () => getFolderChatHistory('4064', { chatId: 'chat' }), oldestFirst: false },
  { name: 'article', id: 'knowledgesearch_a3', load: () => getChannelChatHistory('article'), oldestFirst: true },
])('restores $name history citations through the permission-filtered resolver', async ({ id, load, oldestFirst }) => {
  const rows = [
    { id: 1, is_bot: false, chat_id: 'chat', message: JSON.stringify({ query: 'Question' }) },
    { id: 2, is_bot: true, chat_id: 'chat', message: JSON.stringify({ content: `Answer ${id}:29` }) },
  ];
  (request.get as jest.Mock).mockResolvedValue({ data: oldestFirst ? rows : rows.slice().reverse() });
  (request.post as jest.Mock).mockResolvedValue({ items: [{ citationId: id, type: 'rag', sourcePayload: { items: [{ itemId: '29' }] } }] });
  const messages = await load();
  expect(messages.map(message => message.messageId)).toEqual(['1', '2']);
  expect(request.post).toHaveBeenCalledWith('/api/v1/citations/resolve', { citationIds: [id] }, undefined);
  expect(transformPrivateCitations(messages[1].text, messages[1].citations).transformedContent).toBe(`Answer [citationref:${id}:29]`);
});
