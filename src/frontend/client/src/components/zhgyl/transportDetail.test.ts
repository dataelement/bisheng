import zhTranslation from '../../locales/zh-Hans/translation.json';
import { resolveTransportBinding, stripTransportDetail, transportPayload, transportReference, type TransportVersion } from './transportDetail';

const chatId = 'synthetic-chat';
const toolKey = 'synthetic-transport';
const binding = { contextId: 'a'.repeat(48), queryId: 'b'.repeat(12) };
const version: TransportVersion = { id: 'v1', session_id: chatId, skills: ['transport-native-api'], status: 'completed', tools: [{ children: [{ tool_key: toolKey }] }] };
const tasks = async () => [{ history: [{ step_type: 'tool', name: toolKey, status: 'end', output: { protocol: 'transport-fixed-entry-v1', terminal: true, outcome: 'ok', context_id: binding.contextId, query_id: binding.queryId } }] }];

test('binds a detail request only to the current conversation successful tool call', async () => {
  await expect(resolveTransportBinding(chatId, toolKey, [version], tasks)).resolves.toEqual(binding);
  await expect(resolveTransportBinding('other-chat', toolKey, [version], tasks)).resolves.toBeNull();
  await expect(resolveTransportBinding(chatId, 'other-tool', [version], tasks)).resolves.toBeNull();
});

test('a newer failed transport query blocks borrowing an older bill reference', async () => {
  const getTasks = jest.fn(tasks);
  await expect(resolveTransportBinding(chatId, toolKey, [{ ...version, id: 'newer', status: 'failed' }, version], getTasks)).resolves.toBeNull();
  expect(getTasks).not.toHaveBeenCalled();
});

test('rejects ambiguous calls and malformed context ids', async () => {
  const rows = await tasks();
  await expect(resolveTransportBinding(chatId, toolKey, [version], async () => [...rows, ...rows])).resolves.toBeNull();
  rows[0].history[0].output.context_id = '../other-session';
  await expect(resolveTransportBinding(chatId, toolKey, [version], async () => rows)).resolves.toBeNull();
});

test('protocol metadata is appended once and removed from display text', () => {
  const text = zhTranslation.zhgyl.transportDraft.replace('{{reference}}', 'F01');
  expect(transportReference(text)).toBe('F01');
  const payload = transportPayload(text, 'F01', binding);
  expect(stripTransportDetail(payload)).toBe(text);
  expect(transportPayload(payload, 'F01', binding)).toBe(payload);
  expect(transportReference('ordinary transport question')).toBeNull();
});
