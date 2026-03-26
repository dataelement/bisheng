import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { NotificationSeverity } from '~/common';
import type { AppConversation, ConversationGroup } from '~/@types/app';
import { getAppConversationsApi } from '~/api/apps';
import { groupConversationsByTime, getAppShareUrl } from '~/pages/apps/appUtils';
import { copyText } from '~/utils';
import { useToastContext } from '~/Providers';
import {
  appConversationsState,
  currentAppInfoState,
  sidebarVisibleState,
} from '~/pages/appChat/store/appSidebarAtoms';
import { generateUUID } from '~/utils';

/**
 * Hook for the app chat sidebar.
 * Handles: loading conversations, time grouping, new/switch conversation, sidebar toggle.
 */
export function useAppSidebar() {
  const navigate = useNavigate();
  const { fid: flowId, type: flowType, conversationId } = useParams();
  const { showToast } = useToastContext();
  const showToastRef = useRef(showToast);
  showToastRef.current = showToast;

  const currentApp = useRecoilValue(currentAppInfoState);
  const [conversations, setConversations] = useRecoilState(appConversationsState);
  const [sidebarVisible, setSidebarVisible] = useRecoilState(sidebarVisibleState);

  const [loading, setLoading] = useState(false);

  /** Fetch conversation list for the current app */
  const fetchConversations = useCallback(async () => {
    if (!flowId) return;
    setLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API untyped
      const res: any = await getAppConversationsApi(flowId, 1, 100);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API response shape varies
      const list: AppConversation[] = (res.data?.list || []).map((item: any) => {
        return {
          id: item.chat_id,
          title: item.flow_name || '新对话',
          flowId: item.flow_id || flowId,
          flowType: Number(item.flow_type || flowType),
          updatedAt: item.update_time || '',
          createdAt: item.create_time || '',
        };
      });
      setConversations(list);

      // Notify when no conversation history exists for this app
      if (list.length === 0) {
        showToastRef.current?.({ message: '历史会话已删除', severity: NotificationSeverity.ERROR });
      }
    } catch {
      console.error('Failed to fetch app conversations');
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
    navigate(`/app/${chatId}/${flowId}/${flowType}`);
  }, [flowId, flowType, navigate]);

  /** Switch to a specific conversation */
  const switchConversation = useCallback(
    (conv: AppConversation) => {
      navigate(`/app/${conv.id}/${conv.flowId}/${conv.flowType}`);
    },
    [navigate],
  );

  /** Toggle sidebar visibility */
  const toggleSidebar = useCallback(() => {
    setSidebarVisible((prev) => !prev);
  }, [setSidebarVisible]);

  /** Share the current app */
  const shareApp = useCallback(async () => {
    if (!flowId) return;
    const url = getAppShareUrl(flowId, flowType || '');
    try {
      await copyText(url);
      showToast?.({ message: '已将应用链接复制到剪贴板', severity: NotificationSeverity.SUCCESS });
    } catch {
      showToast?.({ message: '复制失败', severity: NotificationSeverity.ERROR });
    }
  }, [flowId, flowType, showToast]);

  // Auto-fetch on mount or flowId change
  useEffect(() => {
    fetchConversations();
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
