import { useRecoilValue } from 'recoil';
import { QueryKeys, dataService } from '~/types/chat';
import { useQuery } from '@tanstack/react-query';
import type { QueryObserverResult, UseQueryOptions } from '@tanstack/react-query';
import type * as t from '~/types/chat';
import { serviceProbeSettled } from '~/api/request';
import store from '~/store';

export const useGetUserQuery = (
  config?: UseQueryOptions<t.TUser>,
): QueryObserverResult<t.TUser> => {
  const queriesEnabled = useRecoilValue<boolean>(store.queriesEnabled);
  return useQuery<t.TUser>([QueryKeys.user], async () => {
    try {
      return await dataService.getUser();
    } catch (error) {
      // Keep startup auth guards from redirecting while availability is being checked.
      await serviceProbeSettled();
      throw error;
    }
  }, {
    refetchOnWindowFocus: true,
    refetchOnReconnect: false,
    refetchOnMount: false,
    retry: false,
    ...config,
    enabled: (config?.enabled ?? true) === true && queriesEnabled,
  });
};
