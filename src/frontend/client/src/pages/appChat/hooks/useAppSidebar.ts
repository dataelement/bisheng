import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useRecoilState, useRecoilValue, useSetRecoilState } from 'recoil';
import { NotificationSeverity } from '~/common';
import type { AppConversation, AppItem, ConversationGroup } from '~/@types/app';
import { getAppConversationsApi, getAssistantDetailApi, getFlowApi } from '~/api/apps';
import { groupConversationsByTime, getAppShareUrl } from '~/pages/apps/appUtils';
import { copyText } from '~/utils';
import { useToastContext } from '~/Providers';
import {
  appConversationsState,
  currentAppInfoState,
  sidebarVisibleState,
} from '~/pages/appChat/store/appSidebarAtoms';
import { currentChatState } from '~/pages/appChat/store/atoms';
import { generateUUID } from '~/utils';
import { useLocalize } from '~/hooks';

// flow_type 5 === assistant; anything else (1 = skill, 10 = workflow) goes through getFlowApi.
const FLOW_TYPE_ASSISTANT = 5;

/**
 * Hook for the app chat sidebar.
 * Handles: loading conversations, time grouping, new/switch conversation, sidebar toggle.
 */
export function useAppSidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const localize = useLocalize();
  const { fid: flowId, type: flowType, conversationId } = useParams();
  const { showToast } = useToastContext();
  const showToastRef = useRef(showToast);
  showToastRef.current = showToast;

  const currentApp = useRecoilValue(currentAppInfoState);
  const chatState = useRecoilValue(currentChatState);
  const setCurrentApp = useSetRecoilState(currentAppInfoState);
  const [conversations, setConversations] = useRecoilState(appConversationsState);
  const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);

  const [loading, setLoading] = useState(false);
  // Track whether we previously had conversations (to distinguish initial empty from delete-all)
  const hadConversationsRef = useRef(false);

  /** Fetch conversation list for the current app and return it. */
  const fetchConversations = useCallback(async (): Promise<AppConversation[]> => {
    if (!flowId) return [];
    setLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API untyped
      const res: any = await getAppConversationsApi(flowId, 1, 100);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API response shape varies
      const list: AppConversation[] = (res.data?.list || []).map((item: any) => {
        return {
          id: item.chat_id,
          title: item.name || item.flow_name || '新对话',
          flowId: item.flow_id || flowId,
          flowType: Number(item.flow_type || flowType),
          updatedAt: item.update_time || '',
          createdAt: item.create_time || '',
        };
      });
      setConversations(list);

      // Show toast only when user deletes all conversations (non-empty → empty),
      // not on initial load when no history exists
      if (list.length === 0 && hadConversationsRef.current) {
        showToastRef.current?.({ message: '历史会话已删除', severity: NotificationSeverity.ERROR });
      }
      hadConversationsRef.current = list.length > 0;
      return list;
    } catch {
      console.error('Failed to fetch app conversations');
      return [];
    } finally {
      setLoading(false);
    }
  }, [flowId, flowType, setConversations]);

  /** Grouped conversations by time */
  const groups: ConversationGroup[] = groupConversationsByTime(conversations);

  /** Create a new conversation */
  const createNewChat = useCallback(() => {
    if (!flowId || !flowType) return;
    const chatId = generateUUID(32);
    // Prepend a "New Chat" placeholder so the sidebar shows it immediately
    // and the auto-select guard won't redirect away from it.
    setConversations((prev) => [{
      id: chatId,
      title: localize('com_ui_new_chat'),
      flowId: flowId,
      flowType: Number(flowType),
      updatedAt: new Date().toISOString(),
      createdAt: new Date().toISOString(),
    }, ...prev]);
    const from = new URLSearchParams(location.search).get('from');
    const nextPath = from
      ? `/app/${chatId}/${flowId}/${flowType}?from=${from}`
      : `/app/${chatId}/${flowId}/${flowType}`;
    navigate(nextPath);
  }, [flowId, flowType, location.search, navigate, setConversations]);

  /** Switch to a specific conversation */
  const switchConversation = useCallback(
    (conv: AppConversation) => {
      const from = new URLSearchParams(location.search).get('from');
      const nextPath = from
        ? `/app/${conv.id}/${conv.flowId}/${conv.flowType}?from=${from}`
        : `/app/${conv.id}/${conv.flowId}/${conv.flowType}`;
      navigate(nextPath);
    },
    [location.search, navigate],
  );

  /** Toggle sidebar visibility */
  const toggleSidebar = useCallback(() => {
    setSidebarVisible((prev) => !prev);
  }, [setSidebarVisible]);

  /** Share the current app */
  const shareApp = useCallback(async () => {
    if (!flowId) return;
    const fromChat =
      chatState?.flow && String(chatState.flow.id) === String(flowId) ? chatState.flow.can_share : undefined;
    const fromSidebar =
      currentApp && String(currentApp.id) === String(flowId) ? currentApp.can_share : undefined;
    if (fromChat !== true && fromSidebar !== true) return;
    const url = getAppShareUrl(flowId, flowType || '');
    try {
      await copyText(url);
      showToast?.({ message: '已将应用链接复制到剪贴板', severity: NotificationSeverity.SUCCESS });
    } catch {
      showToast?.({ message: '复制失败', severity: NotificationSeverity.ERROR });
    }
  }, [flowId, flowType, showToast, chatState?.flow, currentApp]);

  // Guard: auto-select runs only once per flowId (on initial mount).
  // This prevents re-triggering when the user creates a new chat or switches conversations.
  const hasAutoSelectedRef = useRef<string | null>(null);

  // Fetch flow-level info (name / logo / description) into currentAppInfoState so
  // the sidebar card stays populated even when no chat is active — e.g. right after
  // deleting the active conversation, chatsState briefly loses the flow reference.
  useEffect(() => {
    if (!flowId || !flowType) return;
    const numericType = Number(flowType);
    (async () => {
      try {
        const res = numericType === FLOW_TYPE_ASSISTANT
          ? await getAssistantDetailApi(flowId, undefined, true)
          : await getFlowApi(flowId, 'v1', undefined, true);
        if (res?.status_code !== 200) return;
        const data = res.data;
        if (!data) return;
        setCurrentApp({
          id: data.id ?? flowId,
          name: data.name ?? '',
          description: data.description ?? data.desc ?? '',
          logo: data.logo ?? '',
          flow_type: Number(data.flow_type ?? numericType),
          user_id: data.user_id ?? '',
          can_share: data.can_share === true,
        } as AppItem);
      } catch {
        // silent — sidebar falls back to placeholder text
      }
    })();
  }, [flowId, flowType, setCurrentApp]);

  // Auto-fetch on mount or flowId change, with one-time auto-select
  useEffect(() => {
    fetchConversations().then((list) => {
      // Skip if auto-select already ran for this flowId
      if (hasAutoSelectedRef.current === flowId) return;
      hasAutoSelectedRef.current = flowId!;

      // When the current conversationId doesn't match any existing conversation
      // (e.g. freshly opened from app center with a generated UUID), prepend a
      // placeholder so the sidebar shows it immediately — same as createNewChat.
      if (conversationId && !list.some(c => c.id === conversationId)) {
        setConversations((prev) => [{
          id: conversationId,
          title: localize('com_ui_new_chat'),
          flowId: flowId!,
          flowType: Number(flowType),
          updatedAt: new Date().toISOString(),
          createdAt: new Date().toISOString(),
        }, ...prev]);
      }
    });
    // Only re-run when fetchConversations identity changes (i.e. flowId changes).
    // conversationId is intentionally excluded to prevent re-fetch on every navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchConversations]);

  return {
    currentApp,
    conversations,
    groups,
    loading,
    activeConversationId: conversationId,
    sidebarVisible,
    fetchConversations,
    createNewChat,
    switchConversation,
    toggleSidebar,
    shareApp,
  };
}
