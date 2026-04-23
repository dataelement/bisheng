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
import { copyText, generateUUID } from '~/utils';

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
      setRecentApps(res.data?.list || []);
    } finally {
      setLoading(false);
    }
  }, [setRecentApps]);

  /** Toggle pin state for an app */
  const togglePin = useCallback(
    async (app: AppItem) => {
      const shouldPin = !app.is_pinned;
      try {
        await pinAppApi(app.id, shouldPin);
        // Refresh the list to get updated pin state from backend
        await fetchApps();
      } catch {
        showToast?.({ message: shouldPin ? '置顶失败' : '取消置顶失败', severity: NotificationSeverity.ERROR });
      }
    },
    [fetchApps, showToast],
  );

  /** Navigate into an app — always create a new conversation */
  const continueChat = useCallback(
    (app: AppItem) => {
      const chatId = generateUUID(32);
      navigate(`/app/${chatId}/${app.id}/${app.flow_type}?from=center`);
    },
    [navigate],
  );

  /** Create a new conversation and navigate */
  const startChat = useCallback(
    (app: AppItem) => {
      const chatId = generateUUID(32);
      navigate(`/app/${chatId}/${app.id}/${app.flow_type}?from=center`);
    },
    [navigate],
  );

  /** Copy share link to clipboard */
  const shareApp = useCallback(
    async (app: AppItem) => {
      if (app.can_share !== true) return;
      const url = getAppShareUrl(app.id, app.flow_type);
      try {
        await copyText(url);
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
