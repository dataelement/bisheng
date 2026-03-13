import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { NotificationSeverity } from '~/common';
import type { AppItem } from '~/@types/app';
import { getFrequently, pinAppApi } from '~/api/apps';
import { useToastContext } from '~/Providers';
import { getAppShareUrl } from '~/pages/apps/appUtils';
import {
  appSearchQueryState,
  filteredAppsSelector,
  recentAppsState,
} from '~/pages/apps/store/appCenterAtoms';
import { generateUUID } from '~/utils';

/**
 * Hook for the App Center home page.
 * Handles: fetching apps, search, pin toggle, continue/start chat, share.
 */
export function useAppCenter() {
  const navigate = useNavigate();
  const { showToast } = useToastContext();

  const [, setRecentApps] = useRecoilState(recentAppsState);
  const [searchQuery, setSearchQuery] = useRecoilState(appSearchQueryState);
  const apps = useRecoilValue(filteredAppsSelector);

  const [loading, setLoading] = useState(false);

  /** Fetch apps with recent history */
  const fetchApps = useCallback(async () => {
    setLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API untyped
      const res: any = await getFrequently(1, 50);
      setRecentApps(res.data || []);
    } finally {
      setLoading(false);
    }
  }, [setRecentApps]);

  /** Toggle pin state for an app */
  const togglePin = useCallback(
    async (app: AppItem) => {
      const shouldPin = !app.is_pinned;
      try {
        await pinAppApi(app.flow_type, app.id, shouldPin);
        // Refresh the list to get updated pin state from backend
        await fetchApps();
      } catch {
        showToast?.({  message: shouldPin ? '置顶失败' : '取消置顶失败', severity: NotificationSeverity.ERROR });
      }
    },
    [fetchApps, showToast],
  );

  /** Navigate to the most recent conversation for an app */
  const continueChat = useCallback(
    (app: AppItem) => {
      if (app.last_chat_id) {
        navigate(`/app/${app.last_chat_id}/${app.id}/${app.flow_type}`);
      } else {
        showToast?.({ message: '历史会话已删除', severity: NotificationSeverity.ERROR });
      }
    },
    [navigate, showToast],
  );

  /** Create a new conversation and navigate */
  const startChat = useCallback(
    (app: AppItem) => {
      const chatId = generateUUID(32);
      navigate(`/app/${chatId}/${app.id}/${app.flow_type}`);
    },
    [navigate],
  );

  /** Copy share link to clipboard */
  const shareApp = useCallback(
    async (app: AppItem) => {
      const url = getAppShareUrl(app.id);
      try {
        await navigator.clipboard.writeText(url);
        showToast?.({ message: '已将应用链接复制到剪贴板', severity: NotificationSeverity.SUCCESS });
      } catch {
        showToast?.({ message: '复制失败，请手动复制', severity: NotificationSeverity.ERROR });
      }
    },
    [showToast],
  );

  return {
    apps,
    loading,
    searchQuery,
    setSearchQuery,
    fetchApps,
    togglePin,
    continueChat,
    startChat,
    shareApp,
  };
}
