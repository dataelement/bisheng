import type { QueryObserverResult, UseQueryOptions } from '@tanstack/react-query';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useRecoilValue } from 'recoil';
import { getKnowledgeStatusApi } from '~/api';
import { BsConfig, QueryKeys, TEndpointsConfig, TStartupConfig, dataService } from '~/data-provider/data-provider/src';
import store from '~/store';

export const useGetEndpointsQuery = <TData = TEndpointsConfig>(
  config?: UseQueryOptions<TEndpointsConfig, unknown, TData>,
): QueryObserverResult<TData> => {
  const queriesEnabled = useRecoilValue<boolean>(store.queriesEnabled);
  return useQuery<TEndpointsConfig, unknown, TData>(
    [QueryKeys.endpoints],
    () => dataService.getAIEndpoints(),
    {
      staleTime: Infinity,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: false,
      ...config,
      enabled: (config?.enabled ?? true) === true && queriesEnabled,
    },
  );
};

export const useGetStartupConfig = (
  config?: UseQueryOptions<TStartupConfig>,
): QueryObserverResult<TStartupConfig> => {
  const queriesEnabled = useRecoilValue<boolean>(store.queriesEnabled);
  return useQuery<TStartupConfig>(
    [QueryKeys.startupConfig],
    () => dataService.getStartupConfig(),
    {
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: false,
      ...config,
      enabled: (config?.enabled ?? true) === true && queriesEnabled,
    },
  );
};


export const useGetBsConfig = (
  config?: UseQueryOptions<BsConfig>,
): QueryObserverResult<BsConfig> => {
  const queriesEnabled = useRecoilValue<boolean>(store.queriesEnabled);
  return useQuery<BsConfig>(
    [QueryKeys.bishengConfig],
    () => dataService.getBishengConfig().then(data => {
      // 更新favicon
      const favicon = document.createElement('link');
      favicon.type = 'image/x-icon';
      favicon.rel = 'shortcut icon';
      favicon.href = __APP_ENV__.BASE_URL + data.assistantIcon.image;
      document.head.appendChild(favicon);
      return data;
    }),
    {
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      refetchOnMount: 'always',
      ...config,
      enabled: (config?.enabled ?? true) === true && queriesEnabled,
    },
  );
};

export const useModelBuilding = () => {
  const [shouldPoll, setShouldPoll] = useState(true);

  const { data, refetch } = useQuery({
    queryKey: ['knowledgeStatus'],
    queryFn: async () => {
      const res = await getKnowledgeStatusApi();

      if (res.data?.status === 'success') {
        setShouldPoll(false);
        return false
      }
      return false
    },
    refetchOnWindowFocus: false,
    enabled: shouldPoll, // 由状态控制是否启用查询
    refetchInterval: shouldPoll ? 3000 : false, // 轮询间隔3秒，停止时设为false
  });

  return [data === undefined ? true : data, refetch] as const;
}
