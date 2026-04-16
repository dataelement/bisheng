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
import { useStandaloneChatContext } from '../StandaloneChatContext';
import {
  getLocalConversations,
  addLocalConversation,
  renameLocalConversation as renameLocal,
  deleteLocalConversation as deleteLocal,
} from '../localConversationStore';

const FLOW_TYPE_ASSISTANT = 5;
const FLOW_TYPE_WORKFLOW = 10;

/**
 * Hook for standalone chat sidebar.
 * Guest mode: conversations from localStorage, no server API calls for list/rename/delete.
 * Auth mode: delegates to server APIs (same as useAppSidebar but with different URL scheme).
 */
export function useStandaloneSidebar() {
  const { mode, flowType, flowId, apiVersion } = useStandaloneChatContext();
  const localize = useLocalize();
  const isGuest = mode === 'guest';
  const numericFlowType = flowType === 'assistant' ? FLOW_TYPE_ASSISTANT : FLOW_TYPE_WORKFLOW;

  const currentApp = useRecoilValue(currentAppInfoState);
  const setCurrentApp = useSetRecoilState(currentAppInfoState);
  const [conversations, setConversations] = useRecoilState(appConversationsState);
  const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);
  const [activeChatId, setActiveChatId] = useRecoilState(standaloneChatIdState);
  const setChats = useSetRecoilState(chatsState);
  const setRunning = useSetRecoilState(runningState);

  const [loading, setLoading] = useState(false);
  const initializedRef = useRef(false);

  // Fetch conversation list
  const fetchConversations = useCallback(async (): Promise<AppConversation[]> => {
    if (!flowId) return [];

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
      setConversations(convos);
      return convos;
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
      setConversations(list);
      return list;
    } catch {
      console.error('Failed to fetch standalone conversations');
      return [];
    } finally {
      setLoading(false);
    }
  }, [flowId, isGuest, numericFlowType, setConversations, localize]);

  // Grouped conversations
  const groups: ConversationGroup[] = groupConversationsByTime(conversations);

  // Create new conversation
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

    if (isGuest) {
      addLocalConversation(flowId, { id: chatId, title, updatedAt: now, createdAt: now });
    }

    setConversations((prev) => [conv, ...prev]);
    setActiveChatId(chatId);
  }, [flowId, numericFlowType, isGuest, setConversations, setActiveChatId, localize]);

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

      // If deleting the active conversation, switch to next one
      if (chatId === activeChatId) {
        const remaining = conversations.filter((c) => c.id !== chatId);
        if (remaining.length > 0) {
          setActiveChatId(remaining[0].id);
        } else {
          // Create a fresh conversation
          createNewChat();
        }
      }
    },
    [flowId, isGuest, activeChatId, conversations, setChats, setRunning, setConversations, setActiveChatId, createNewChat],
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

  // Initialize: fetch conversations and resolve initial chatId
  useEffect(() => {
    console.log('[standalone] init effect:', { flowId, initialized: initializedRef.current });
    if (initializedRef.current || !flowId) return;
    initializedRef.current = true;

    fetchConversations().then((list) => {
      if (list.length > 0) {
        setActiveChatId(list[0].id);
      } else {
        createNewChat();
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowId]);

  return {
    currentApp,
    conversations,
    groups,
    loading,
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
