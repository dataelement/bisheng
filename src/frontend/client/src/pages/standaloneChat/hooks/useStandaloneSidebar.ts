import { useCallback, useEffect, useRef, useState } from 'react';
import { useRecoilState, useRecoilValue, useSetRecoilState } from 'recoil';
import type { AppConversation, AppItem, ConversationGroup } from '~/@types/app';
import { getAppConversationsApi, getAssistantDetailApi, getFlowApi } from '~/api/apps';
import { groupConversationsByTime } from '~/pages/apps/appUtils';
import { generateUUID } from '~/utils';
import { useLocalize } from '~/hooks';
import {
  appConversationsState,
  currentAppInfoState,
  sidebarVisibleState,
} from '~/pages/appChat/store/appSidebarAtoms';
import { chatsState, runningState } from '~/pages/appChat/store/atoms';
import { closeAppChatWebSocket } from '~/pages/appChat/useWebsocket';
import { standaloneChatIdState } from '../store/atoms';
import type { StandaloneChatContextValue } from '../StandaloneChatContext';
import {
  getLocalConversations,
  addLocalConversation,
  renameLocalConversation as renameLocal,
  deleteLocalConversation as deleteLocal,
} from '../localConversationStore';

// Module-level draft registry: conversation ids that exist only in memory and
// have not yet been persisted (guest: localStorage, auth: server via first
// message). Survives component unmounts within the same page session so that
// remounting the sidebar hook doesn't duplicate drafts.
const draftChatIds = new Set<string>();

const FLOW_TYPE_ASSISTANT = 5;
const FLOW_TYPE_WORKFLOW = 10;

/**
 * Hook for standalone chat sidebar.
 * Guest mode: conversations from localStorage, no server API calls for list/rename/delete.
 * Auth mode: delegates to server APIs (same as useAppSidebar but with different URL scheme).
 */
export function useStandaloneSidebar(ctx: StandaloneChatContextValue) {
  const { mode, flowType, flowId, apiVersion } = ctx;
  const localize = useLocalize();
  const isGuest = mode === 'guest';
  const numericFlowType = flowType === 'assistant' ? FLOW_TYPE_ASSISTANT : FLOW_TYPE_WORKFLOW;

  const currentApp = useRecoilValue(currentAppInfoState);
  const setCurrentApp = useSetRecoilState(currentAppInfoState);
  const [conversations, setConversations] = useRecoilState(appConversationsState);
  const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);
  const [activeChatId, setActiveChatId] = useRecoilState(standaloneChatIdState);
  const [chats, setChats] = useRecoilState(chatsState);
  const setRunning = useSetRecoilState(runningState);

  const [loading, setLoading] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const initializedRef = useRef(false);
  // Snapshot of latest conversations for draft-preservation in async callbacks
  const conversationsRef = useRef<AppConversation[]>(conversations);
  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  // Fetch conversation list
  const fetchConversations = useCallback(async (): Promise<AppConversation[]> => {
    if (!flowId) return [];

    // Merge fetched list with any in-memory drafts (conversations created via
    // createNewChat() but not yet persisted). Without this merge, a refetch
    // triggered by rename/delete would wipe unsent drafts from the sidebar.
    const preserveDrafts = (fetched: AppConversation[]): AppConversation[] => {
      if (draftChatIds.size === 0) return fetched;
      const fetchedIds = new Set(fetched.map((c) => c.id));
      const drafts = conversationsRef.current.filter(
        (c) => draftChatIds.has(c.id) && !fetchedIds.has(c.id),
      );
      return [...drafts, ...fetched];
    };

    if (isGuest) {
      const local = getLocalConversations(flowId);
      const convos: AppConversation[] = local.map((c) => ({
        id: c.id,
        title: c.title,
        flowId,
        flowType: numericFlowType,
        updatedAt: c.updatedAt,
        createdAt: c.createdAt,
      }));
      const merged = preserveDrafts(convos);
      setConversations(merged);
      return merged;
    }

    // Auth mode: fetch from server
    setLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const res: any = await getAppConversationsApi(flowId, 1, 100);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const list: AppConversation[] = (res.data?.list || []).map((item: any) => ({
        id: item.chat_id,
        title: item.name || item.flow_name || localize('com_ui_new_chat'),
        flowId: item.flow_id || flowId,
        flowType: Number(item.flow_type || numericFlowType),
        updatedAt: item.update_time || '',
        createdAt: item.create_time || '',
      }));
      const merged = preserveDrafts(list);
      setConversations(merged);
      return merged;
    } catch {
      console.error('Failed to fetch standalone conversations');
      return [];
    } finally {
      setLoading(false);
    }
  }, [flowId, isGuest, numericFlowType, setConversations, localize]);

  // Grouped conversations
  const groups: ConversationGroup[] = groupConversationsByTime(conversations);

  // Create new conversation (as draft — not persisted until first user message)
  const createNewChat = useCallback(() => {
    if (!flowId) return;
    const chatId = generateUUID(32);
    const now = new Date().toISOString();
    const title = localize('com_ui_new_chat');

    const conv: AppConversation = {
      id: chatId,
      title,
      flowId,
      flowType: numericFlowType,
      updatedAt: now,
      createdAt: now,
    };

    // Do not persist yet (guest localStorage / server). Mark as draft so the
    // first-user-message effect below can commit it when the user actually
    // sends something. This prevents empty conversations from polluting the
    // history list if the user navigates away without sending (TC-APP-PUB-019).
    draftChatIds.add(chatId);
    setConversations((prev) => [conv, ...prev]);
    setActiveChatId(chatId);
  }, [flowId, numericFlowType, setConversations, setActiveChatId, localize]);

  // Switch to a conversation
  const switchConversation = useCallback(
    (conv: AppConversation) => {
      setActiveChatId(conv.id);
    },
    [setActiveChatId],
  );

  // Rename a conversation
  const renameConversation = useCallback(
    (chatId: string, newTitle: string) => {
      if (isGuest) {
        renameLocal(flowId, chatId, newTitle);
      }
      setConversations((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, title: newTitle } : c)),
      );
    },
    [flowId, isGuest, setConversations],
  );

  // Delete a conversation
  const deleteConversation = useCallback(
    (chatId: string) => {
      if (isGuest) {
        deleteLocal(flowId, chatId);
      }
      draftChatIds.delete(chatId);
      // Clean up websocket and recoil state
      closeAppChatWebSocket(chatId);
      setChats((prev) => {
        if (!(chatId in prev)) return prev;
        const next = { ...prev };
        delete next[chatId];
        return next;
      });
      setRunning((prev) => {
        if (!(chatId in prev)) return prev;
        const next = { ...prev };
        delete next[chatId];
        return next;
      });
      setConversations((prev) => prev.filter((c) => c.id !== chatId));

      // If deleting the active conversation, fall back to next one or empty state
      if (chatId === activeChatId) {
        const remaining = conversations.filter((c) => c.id !== chatId);
        if (remaining.length > 0) {
          setActiveChatId(remaining[0].id);
        } else {
          setActiveChatId('');
        }
      }
    },
    [flowId, isGuest, activeChatId, conversations, setChats, setRunning, setConversations, setActiveChatId],
  );

  // Toggle sidebar
  const toggleSidebar = useCallback(() => {
    setSidebarVisible((prev) => !prev);
  }, [setSidebarVisible]);

  // Fetch flow-level info (name, logo, description)
  useEffect(() => {
    console.log('[standalone] flow detail effect:', { flowId, numericFlowType, apiVersion });
    if (!flowId) return;
    (async () => {
      try {
        console.log('[standalone] fetching flow detail...');
        const res = numericFlowType === FLOW_TYPE_ASSISTANT
          ? await getAssistantDetailApi(flowId, undefined, true, apiVersion)
          : await getFlowApi(flowId, apiVersion, undefined, true);
        console.log('[standalone] flow detail response:', res);
        if (res?.status_code !== 200) return;
        const data = res.data;
        if (!data) return;
        setCurrentApp({
          id: data.id ?? flowId,
          name: data.name ?? '',
          description: data.description ?? '',
          logo: data.logo ?? '',
          flow_type: Number(data.flow_type ?? numericFlowType),
          user_id: data.user_id ?? '',
        } as AppItem);
      } catch (err) {
        console.error('[standalone] Failed to fetch app detail:', err);
      }
    })();
  }, [flowId, numericFlowType, apiVersion, setCurrentApp]);

  // Initialize: fetch conversations only. Do NOT auto-create a new chat when
  // the list is empty — the page renders an empty-state CTA (TC-APP-PUB-013/014/015)
  // that invokes createNewChat() on user click.
  useEffect(() => {
    if (initializedRef.current || !flowId) return;
    initializedRef.current = true;

    fetchConversations().then((list) => {
      if (list.length > 0) {
        setActiveChatId(list[0].id);
      }
      setHistoryLoaded(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowId]);

  // Persist draft conversation to localStorage/server once the user sends
  // their first message (detected by the presence of an `isSend` message in
  // chatsState). This enforces TC-APP-PUB-019: no message sent = no entry in
  // the history list.
  useEffect(() => {
    if (draftChatIds.size === 0) return;
    draftChatIds.forEach((draftId) => {
      const chat = chats[draftId];
      // Runtime-sent messages set `category: 'question'` (createSendMsg) but
      // not `isSend`; history-fetched messages set both. Check either to cover
      // both cases — relying on `isSend` alone misses live drafts.
      const hasUserMessage = chat?.messages?.some(
        (m) => m.isSend || m.category === 'question',
      );
      if (!hasUserMessage) return;

      draftChatIds.delete(draftId);
      if (!isGuest) return; // Auth mode: server creates the conversation on first message

      const conv = conversations.find((c) => c.id === draftId);
      if (!conv) return;
      addLocalConversation(flowId, {
        id: conv.id,
        title: conv.title,
        updatedAt: new Date().toISOString(),
        createdAt: conv.createdAt,
      });
    });
  }, [chats, conversations, flowId, isGuest]);

  return {
    currentApp,
    conversations,
    groups,
    loading,
    historyLoaded,
    activeChatId,
    sidebarVisible,
    fetchConversations,
    createNewChat,
    switchConversation,
    renameConversation,
    deleteConversation,
    toggleSidebar,
  };
}
