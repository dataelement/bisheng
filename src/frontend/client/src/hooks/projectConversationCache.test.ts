import { QueryClient } from '@tanstack/react-query';
import type { ProjectSnapshot } from '~/api/chatProjects';
import type { TConversation } from '~/types/chat';
import { cacheCreatedProjectConversation, updateProjectConversationTitle } from './projectConversationCache';

const identity = 'http://localhost:1:7';
const snapshotKey = ['chat-projects', identity];
const listKey = ['chat-projects-conversations', identity, 'project-one', ''];
const chat = (conversationId: string, title = 'New chat') => ({ conversationId, title }) as TConversation;
const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: Infinity } } });
beforeEach(() => {
  client.clear();
  client.setQueryData<ProjectSnapshot>(snapshotKey, {
    identity: { tenant_id: 1, user_id: 7 }, projects: [{ id: 'project-one', name: 'Project' }], memberships: [],
  });
});
afterAll(() => client.clear());

it('keeps pagination and prevents duplicates when creation is confirmed more than once', () => {
  client.setQueryData(listKey, { pages: [
    { data: [chat('older')], total: 2, next_cursor: '1' },
    { data: [chat('oldest')], total: 2, next_cursor: null },
  ], pageParams: [undefined, '1'] });
  cacheCreatedProjectConversation(client, identity, 'project-one', chat('created'));
  cacheCreatedProjectConversation(client, identity, 'project-one', chat('created'));
  expect(client.getQueryData(listKey)).toEqual({ pages: [
    { data: [chat('created'), chat('older')], total: 3, next_cursor: '1' },
    { data: [chat('oldest')], total: 3, next_cursor: null },
  ], pageParams: [undefined, '1'] });
  expect(client.getQueryData<ProjectSnapshot>(snapshotKey)?.memberships).toHaveLength(1);
});

it('cancels stale project reads so their late responses cannot erase the created row or membership', async () => {
  client.setQueryData(listKey, { pages: [{ data: [], total: 0, next_cursor: null }], pageParams: [undefined] });
  const oldSnapshot = client.getQueryData(snapshotKey);
  let resolveSnapshot!: (value: unknown) => void;
  let resolveList!: (value: unknown) => void;
  const snapshotFetch = client.fetchQuery({ queryKey: snapshotKey, queryFn: () => new Promise(resolve => { resolveSnapshot = resolve; }) }).catch(() => undefined);
  const listFetch = client.fetchQuery({ queryKey: listKey, queryFn: () => new Promise(resolve => { resolveList = resolve; }) }).catch(() => undefined);
  cacheCreatedProjectConversation(client, identity, 'project-one', chat('created'));
  resolveSnapshot(oldSnapshot);
  resolveList({ pages: [{ data: [], total: 0, next_cursor: null }], pageParams: [undefined] });
  await Promise.all([snapshotFetch, listFetch]);
  expect(client.getQueryData<ProjectSnapshot>(snapshotKey)?.memberships).toEqual([{ chat_id: 'created', project_id: 'project-one' }]);
  expect(client.getQueryData(listKey)).toMatchObject({ pages: [{ data: [chat('created')] }] });
});

it('seeds a cold project list and leaves other accounts and search results untouched', () => {
  const otherKey = ['chat-projects-conversations', 'other-account', 'project-one', ''];
  const searchKey = ['chat-projects-conversations', identity, 'project-one', 'unrelated search'];
  const empty = { pages: [{ data: [], total: 0, next_cursor: null }], pageParams: [undefined] };
  client.setQueryData(otherKey, empty);
  client.setQueryData(searchKey, empty);
  cacheCreatedProjectConversation(client, identity, 'project-one', chat('created'));
  expect(client.getQueryData(listKey)).toMatchObject({ pages: [{ data: [chat('created')] }] });
  expect(client.getQueryData(otherKey)).toEqual(empty);
  expect(client.getQueryData(searchKey)).toEqual(empty);
  updateProjectConversationTitle(client, identity, 'created', 'Generated title');
  expect(client.getQueryData(listKey)).toMatchObject({ pages: [{ data: [chat('created', 'Generated title')] }] });
});

it('does not undo a later explicit move or publish a draft without a real chat id', () => {
  client.setQueryData<ProjectSnapshot>(snapshotKey, current => current && ({
    ...current, memberships: [{ chat_id: 'created', project_id: 'another-project' }],
  }));
  cacheCreatedProjectConversation(client, identity, 'project-one', chat('created'));
  cacheCreatedProjectConversation(client, identity, 'project-one', chat('new'));
  expect(client.getQueryData(listKey)).toBeUndefined();
  expect(client.getQueryData<ProjectSnapshot>(snapshotKey)?.memberships).toEqual([{ chat_id: 'created', project_id: 'another-project' }]);
});
