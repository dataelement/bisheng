import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSpaceExitStatus, resolveSpaceExitScope } from '~/api/knowledgeSpaceExit';
import { useAuthContext } from '~/hooks';

/** Eligibility is always server-owned; cached or unresolved data cannot authorize exit. */
export function useSpaceExitStatus(spaceId: string, active = true) {
  const { user } = useAuthContext();
  const userId = user?.id == null ? '' : String(user.id);
  const [requested, setRequested] = useState(false);
  const [scopeRevision, setScopeRevision] = useState(0);
  useEffect(() => {
    const invalidate = () => setScopeRevision((value) => value + 1);
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'bs:management-scope') invalidate();
    };
    window.addEventListener('bisheng:management-scope-changed', invalidate);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener('bisheng:management-scope-changed', invalidate);
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  const enabled = !!userId && !!spaceId && (active || requested);
  const scope = useQuery({
    queryKey: ['space-exit-scope', userId, scopeRevision],
    queryFn: resolveSpaceExitScope,
    enabled,
    cacheTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const status = useQuery({
    queryKey: ['space-exit-status', userId, scope.data, scopeRevision, spaceId],
    queryFn: () => getSpaceExitStatus(spaceId),
    enabled: enabled && scope.isSuccess && !scope.isFetching,
    cacheTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const refresh = async () => {
    setRequested(true);
    if (!enabled) return;
    if (scope.isSuccess && !scope.isFetching) {
      await status.refetch();
    } else {
      // Resolving the scope enables the status query; do not also refetch it here.
      await scope.refetch();
    }
  };
  return {
    canExit: enabled && scope.isSuccess && !scope.isFetching && status.isSuccess &&
      !status.isFetching && status.data?.can_exit === true && status.data.reason === null,
    loading: enabled && (scope.isFetching || status.isFetching),
    refresh,
  };
}
