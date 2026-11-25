import type { InfiniteData, QueryClient } from '@tanstack/react-query';
import type { ProjectConversationPage, ProjectSnapshot } from '~/api/chatProjects';
import type { TConversation } from '~/types/chat';

/** Publish only after the server confirms creation and its transactional membership. */
export function cacheCreatedProjectConversation(
  client: QueryClient, identity: string, projectId: string, conversation: TConversation,
) {
  if (!identity || !conversation.conversationId || conversation.conversationId === 'new') return;
  const chatId = conversation.conversationId;
  const snapshotKey = ['chat-projects', identity];
  const snapshot = client.getQueryData<ProjectSnapshot>(snapshotKey);
  const membership = snapshot?.memberships.find(item => item.chat_id === chatId);
  // A repeated creation event must not undo a later explicit move.
  if (membership && membership.project_id !== projectId) return;
  // Cancel older reads before publishing, so they cannot replace the new row.
  void client.cancelQueries({ queryKey: snapshotKey, exact: true });
  client.setQueryData<ProjectSnapshot>(snapshotKey, current => current ? {
    ...current,
    memberships: current.memberships.some(item => item.chat_id === chatId)
      ? current.memberships : [...current.memberships, { chat_id: chatId, project_id: projectId }],
  } : current);
  const listKey = ['chat-projects-conversations', identity, projectId, ''];
  const hasList = Boolean(client.getQueryData<InfiniteData<ProjectConversationPage>>(listKey)?.pages.length);
  void client.cancelQueries({ queryKey: listKey, exact: true });
  client.setQueryData<InfiniteData<ProjectConversationPage>>(listKey, current => {
    if (!current?.pages.length) return {
      pages: [{ data: [conversation], total: 1, next_cursor: null }], pageParams: [undefined],
    };
    const exists = current.pages.some(page => page.data.some(row => row.conversationId === chatId));
    return {
      ...current,
      pages: current.pages.map((page, index) => ({
        ...page,
        total: page.total + (exists ? 0 : 1),
        data: index === 0
          ? [conversation, ...page.data.filter(row => row.conversationId !== chatId)]
          : page.data.filter(row => row.conversationId !== chatId),
      })),
    };
  });
  if (!snapshot) void client.invalidateQueries({ queryKey: snapshotKey, exact: true });
  if (!hasList) void client.invalidateQueries({ queryKey: listKey, exact: true });
}

/** Titles arrive after creation; update every loaded project/search page in this account. */
export function updateProjectConversationTitle(client: QueryClient, identity: string, chatId: string, title: string) {
  if (!identity) return;
  client.setQueriesData<InfiniteData<ProjectConversationPage>>(
    { queryKey: ['chat-projects-conversations', identity] },
    current => current && ({ ...current, pages: current.pages.map(page => ({
      ...page, data: page.data.map(row => row.conversationId === chatId ? { ...row, title } : row),
    })) }),
  );
}
