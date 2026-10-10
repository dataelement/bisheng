import { useCallback, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { NotificationSeverity } from '~/common';
import type { AppItem } from '~/@types/app';
import { getFrequently, pinAppApi } from '~/api/apps';
import { useToastContext } from '~/Providers';
import { useLocalize } from '~/hooks';
import { getAppShareUrl } from '~/pages/apps/appUtils';
import {
  appSearchQueryState,
  filteredAppsSelector,
  recentAppsState,
} from '~/pages/apps/store/appCenterAtoms';
import { normalizeAppChatReturn, writeAppChatOrigin, writeAppChatReturnTo } from '~/pages/appChat/appChatOrigin';
import { copyText, generateUUID } from '~/utils';

const APP_CENTER_PAGE_SIZE = 20;

function mergeAppsById(existing: AppItem[], incoming: AppItem[]) {
  const seenIds = new Set(existing.map((app) => String(app.id)));
  return [
    ...existing,
    ...incoming.filter((app) => {
      const id = String(app.id);
      if (seenIds.has(id)) return false;
      seenIds.add(id);
      return true;
    }),
  ];
}

/**
 * Hook for the App Center home page.
 * Handles: fetching apps, search, pin toggle, continue/start chat, share.
 */
export function useAppCenter() {
  const navigate = useNavigate();
  const location = useLocation();
  const { showToast } = useToastContext();
  const localize = useLocalize();
  const appFlowOriginKey = (flowId: string) => `app-flow-origin:${flowId}`;
  const appLastOriginKey = 'app-last-origin';

  const [, setRecentApps] = useRecoilState(recentAppsState);
  const [searchQuery, setSearchQuery] = useRecoilState(appSearchQueryState);
  const apps = useRecoilValue(filteredAppsSelector);

  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const appsRef = useRef<AppItem[]>([]);
  const requestSeqRef = useRef(0);

  /** Fetch apps with recent history */
  const fetchApps = useCallback(async (nextPage: number = 1, isAppend: boolean = false) => {
    const requestId = ++requestSeqRef.current;
    if (isAppend) {
      setLoadingMore(true);
      setLoadMoreError(false);
    } else {
      setLoading(true);
      setLoadingMore(false);
      setLoadError(false);
      setLoadMoreError(false);
      appsRef.current = [];
      setRecentApps([]);
    }

    try {
      const res: unknown = await getFrequently(nextPage, APP_CENTER_PAGE_SIZE);
      if (requestId !== requestSeqRef.current) return;

      const payload = ((res as { data?: { list?: AppItem[]; total?: number } })?.data ?? {}) as { list?: AppItem[]; total?: number };
      const list = Array.isArray(payload.list) ? payload.list : [];
      const total = Number(payload.total ?? 0);
      const previous = isAppend ? appsRef.current : [];
      const nextApps = isAppend ? mergeAppsById(previous, list) : list;
      const uniqueAddedCount = nextApps.length - previous.length;

      if (nextApps.length < total && (list.length === 0 || (isAppend && uniqueAddedCount === 0))) {
        if (isAppend) setLoadMoreError(true);
        else setLoadError(true);
        setHasMore(false);
        return;
      }

      appsRef.current = nextApps;
      setRecentApps(nextApps);
      setPage(nextPage);
      setHasMore(nextApps.length < total);
    } catch (error) {
      console.error('Failed to load app center list:', error);
      if (requestId !== requestSeqRef.current) return;
      if (isAppend) {
        setLoadMoreError(true);
      } else {
        appsRef.current = [];
        setRecentApps([]);
        setLoadError(true);
      }
      setHasMore(false);
    } finally {
      if (requestId === requestSeqRef.current) {
        if (isAppend) setLoadingMore(false);
        else setLoading(false);
      }
    }
  }, [setRecentApps]);

  const loadMore = useCallback(() => {
    if (loading || loadingMore || loadMoreError || !hasMore) return;
    fetchApps(page + 1, true);
  }, [fetchApps, hasMore, loadMoreError, loading, loadingMore, page]);

  /** Toggle pin state for an app */
  const togglePin = useCallback(
    async (app: AppItem) => {
      const shouldPin = !app.is_pinned;
      try {
        await pinAppApi(app.id, shouldPin);
        // Refresh the list to get updated pin state from backend
        await fetchApps();
      } catch {
        showToast?.({
          message: shouldPin ? localize('com_app_pin_failed') : localize('com_app_unpin_failed'),
          severity: NotificationSeverity.ERROR,
        });
      }
    },
    [fetchApps, localize, showToast],
  );

  /** Navigate into an app — always create a new conversation */
  const continueChat = useCallback(
    (app: AppItem) => {
      const chatId = generateUUID(32);
      const returnTo = normalizeAppChatReturn(location.pathname) ?? '/apps';
      writeAppChatOrigin(chatId, 'center');
      if (returnTo === '/apps') writeAppChatReturnTo(chatId, returnTo);
      try {
        sessionStorage.setItem(appFlowOriginKey(String(app.id)), 'center');
        sessionStorage.setItem(appLastOriginKey, 'center');
      } catch {
        // ignore storage failures
      }
      navigate(`/app/${chatId}/${app.id}/${app.flow_type}?from=center&returnTo=${encodeURIComponent(returnTo)}`, {
        state: { appSurfaceReturn: returnTo },
      });
    },
    [location.pathname, navigate],
  );

  /** Create a new conversation and navigate */
  const startChat = useCallback(
    (app: AppItem) => {
      const chatId = generateUUID(32);
      const returnTo = normalizeAppChatReturn(location.pathname) ?? '/apps';
      writeAppChatOrigin(chatId, 'center');
      if (returnTo === '/apps') writeAppChatReturnTo(chatId, returnTo);
      try {
        sessionStorage.setItem(appFlowOriginKey(String(app.id)), 'center');
        sessionStorage.setItem(appLastOriginKey, 'center');
      } catch {
        // ignore storage failures
      }
      navigate(`/app/${chatId}/${app.id}/${app.flow_type}?from=center&returnTo=${encodeURIComponent(returnTo)}`, {
        state: { appSurfaceReturn: returnTo },
      });
    },
    [location.pathname, navigate],
  );

  /** Copy share link to clipboard */
  const shareApp = useCallback(
    async (app: AppItem) => {
      if (app.can_share !== true) return;
      const url = getAppShareUrl(app.id, app.flow_type);
      try {
        await copyText(url);
        showToast?.({ message: localize('com_app_share_link_copied'), severity: NotificationSeverity.SUCCESS });
      } catch {
        showToast?.({ message: localize('com_app_share_link_copy_failed'), severity: NotificationSeverity.ERROR });
      }
    },
    [localize, showToast],
  );

  return {
    apps,
    loading,
    loadingMore,
    loadError,
    loadMoreError,
    hasMore,
    searchQuery,
    setSearchQuery,
    fetchApps,
    loadMore,
    togglePin,
    continueChat,
    startChat,
    shareApp,
  };
}
