import { useQuery } from '@tanstack/react-query';
import { getChannelsApi, SortType } from '~/api/channels';

interface ChannelListOptions {
  enabled?: boolean;
  createdOrder?: SortType;
  subscribedOrder?: SortType;
}

export function useChannelLists({ enabled = true, createdOrder = SortType.RECENT_UPDATE, subscribedOrder = SortType.RECENT_UPDATE }: ChannelListOptions = {}) {
  const created = useQuery({ queryKey: ['channels', 'created', createdOrder], queryFn: () => getChannelsApi({ type: 'created', sortBy: createdOrder }), enabled, placeholderData: prev => prev });
  const subscribed = useQuery({ queryKey: ['channels', 'subscribed', subscribedOrder], queryFn: () => getChannelsApi({ type: 'subscribed', sortBy: subscribedOrder }), enabled, placeholderData: prev => prev });
  return { created, subscribed, error: created.error ?? subscribed.error,
    retry: () => { void Promise.allSettled([created.refetch(), subscribed.refetch()]); } };
}
