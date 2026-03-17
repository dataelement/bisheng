import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { AppItem } from '~/@types/app';
import { getAllAccessibleAppsApi } from '~/api/apps';
import { generateUUID } from '~/utils';

/**
 * Hook for the app switcher dropdown.
 * Handles: loading accessible apps, search filtering, switching apps.
 */
export function useAppSwitcher() {
  const navigate = useNavigate();
  const { fid: currentFlowId } = useParams();

  const [allApps, setAllApps] = useState<AppItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  console.log('allApps :>> ', allApps);

  /** Fetch all accessible apps (backend returns sorted by last_chat_time desc) */
  const fetchApps = useCallback(async () => {
    setLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- API untyped
      const res: any = await getAllAccessibleAppsApi({ page: 1, limit: 200 });
      setAllApps(res.data || []);
    } catch {
      console.error('Failed to fetch accessible apps');
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch on first open
  useEffect(() => {
    if (allApps.length === 0) {
      fetchApps();
    }
  }, [allApps.length, fetchApps]);

  /** Filtered apps by search query (name only) */
  const filteredApps = useMemo(() => {
    if (!searchQuery) return allApps;
    const q = searchQuery.toLowerCase();
    return allApps.filter((a) => a.name.toLowerCase().includes(q));
  }, [allApps, searchQuery]);

  /** Whether the switch button should be disabled */
  const disabled = allApps.length <= 1;

  /** Switch to a target app */
  const switchApp = useCallback(
    (app: AppItem) => {
      setOpen(false);
      setSearchQuery('');

      if (app.last_chat_id) {
        // Has history: go to the most recent conversation
        navigate(`/app/${app.last_chat_id}/${app.id}/${app.flow_type}`);
      } else {
        // No history: create a new conversation
        const chatId = generateUUID(32);
        navigate(`/app/${chatId}/${app.id}/${app.flow_type}`);
      }
    },
    [navigate],
  );

  return {
    allApps: filteredApps,
    searchQuery,
    setSearchQuery,
    loading,
    open,
    setOpen,
    disabled,
    currentFlowId,
    switchApp,
  };
}
