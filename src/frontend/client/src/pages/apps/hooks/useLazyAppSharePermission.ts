import { useQuery } from '@tanstack/react-query';
import { useCallback } from 'react';
import type { AppItem } from '~/@types/app';
import { checkResourceAction, type ResourceType } from '~/api/permission';

type AppPermissionResourceType = Extract<ResourceType, 'workflow' | 'assistant'>;

const SHARE_PERMISSION_STALE_TIME_MS = 5 * 60 * 1000;

export function getAppPermissionResourceType(flowType: number): AppPermissionResourceType | null {
  if (flowType === 10) return 'workflow';
  if (flowType === 5) return 'assistant';
  return null;
}

/** Resolve an app's share action only after its card becomes interactive. */
export function useLazyAppSharePermission(
  app: Pick<AppItem, 'id' | 'flow_type' | 'can_share'>,
) {
  const resourceType = getAppPermissionResourceType(app.flow_type);
  const {
    data: queriedCanShare,
    isFetching,
    isStale,
    refetch,
  } = useQuery({
    queryKey: ['app-share-permission', resourceType, String(app.id)],
    queryFn: async () => {
      if (!resourceType) return false;
      const result = await checkResourceAction({
        resource_type: resourceType,
        resource_id: String(app.id),
        action: 'share',
      });
      return result.allowed;
    },
    enabled: false,
    initialData: app.can_share,
    staleTime: SHARE_PERMISSION_STALE_TIME_MS,
    retry: false,
  });

  const ensureSharePermission = useCallback(async () => {
    if (app.can_share !== undefined || !resourceType || isFetching) return;
    if (queriedCanShare !== undefined && !isStale) return;
    await refetch();
  }, [app.can_share, isFetching, isStale, queriedCanShare, refetch, resourceType]);

  return {
    canShare: app.can_share ?? queriedCanShare ?? false,
    ensureSharePermission,
  };
}
