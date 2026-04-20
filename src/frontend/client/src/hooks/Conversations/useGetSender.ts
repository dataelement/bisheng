import { useCallback } from 'react';
import { getResponseSender } from '~/types/chat';
import type { TEndpointOption, TEndpointsConfig } from '~/types/chat';
import { useGetEndpointsQuery } from '~/hooks/queries/data-provider';

export default function useGetSender() {
  const { data: endpointsConfig = {} as TEndpointsConfig } = useGetEndpointsQuery();
  return useCallback(
    (endpointOption: TEndpointOption) => {
      const { modelDisplayLabel } = endpointsConfig?.[endpointOption.endpoint ?? ''] ?? {};
      return getResponseSender({ ...endpointOption, modelDisplayLabel });
    },
    [endpointsConfig],
  );
}
