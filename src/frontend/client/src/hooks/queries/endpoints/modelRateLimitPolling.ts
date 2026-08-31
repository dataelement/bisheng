import type { QueryClient } from '@tanstack/react-query';
import { QueryKeys, type BsConfig } from '~/types/chat';

interface ModelRateLimitEvent {
  errorType?: string;
  modelId?: string | number;
  rateLimitState?: 'normal' | 'recovering' | 'busy';
}

type ModelRateLimitState = NonNullable<BsConfig['models'][number]['rateLimitState']>;

export function resolveDisplayedModelRateLimitState(
  models: BsConfig['models'] | undefined,
  modelId: string | number | undefined,
  eventState?: ModelRateLimitState,
): ModelRateLimitState {
  return models?.find((model) => String(model.id) === String(modelId))?.rateLimitState
    ?? (eventState === 'recovering' ? 'recovering' : 'busy');
}

export function getModelRateLimitRefetchInterval(data?: BsConfig): 5000 | false {
  return data?.models?.some(
    (model) => model.rateLimitState === 'busy' || model.rateLimitState === 'recovering',
  )
    ? 5000
    : false;
}

/**
 * Start model-state polling as soon as a typed 429 reaches the UI.
 *
 * The server remains the source of truth: the local projection only prevents a
 * cached `normal` config from hiding the fresh SSE/WS state while the immediate
 * refetch is in flight. Later polls replace it with the Redis-backed projection.
 */
export function observeModelRateLimitEvent(
  queryClient: QueryClient,
  event?: ModelRateLimitEvent,
): void {
  if (
    event?.errorType !== 'rate_limit'
    || event.modelId == null
    || event.rateLimitState == null
  ) return;

  queryClient.setQueryData<BsConfig>([QueryKeys.bishengConfig], (current) => {
    if (!current) return current;
    return {
      ...current,
      models: current.models.map((model) => (
        String(model.id) === String(event.modelId)
          ? { ...model, rateLimitState: event.rateLimitState }
          : model
      )),
    };
  });
  void queryClient.invalidateQueries([QueryKeys.bishengConfig]);
}
