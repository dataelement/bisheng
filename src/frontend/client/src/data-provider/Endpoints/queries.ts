import { useRecoilValue } from 'recoil';
import { QueryKeys, dataService } from '~/data-provider/data-provider/src';
import { useQuery } from '@tanstack/react-query';
import type { QueryObserverResult, UseQueryOptions } from '@tanstack/react-query';
import { TEndpointsConfig, TStartupConfig, BsConfig } from '~/data-provider/data-provider/src';
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
      refetchOnMount: false,
      ...config,
      enabled: (config?.enabled ?? true) === true && queriesEnabled,
    },
  );
};