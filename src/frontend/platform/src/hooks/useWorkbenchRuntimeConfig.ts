import { shouldRetryApiError } from '@bisheng/api-client';
import { useQuery } from '@tanstack/react-query';
import { getLinsightModelConfig } from '@/controllers/API/finetune';
import { showApiError } from '@/controllers/request';

/** Runtime consumers use projected configuration, never editable model settings. */
export function useWorkbenchRuntimeConfig() {
  return useQuery({
    queryKey: ['workbenchRuntimeConfig'],
    queryFn: getLinsightModelConfig,
    onError: showApiError,
    retry: (failureCount, error) => shouldRetryApiError(error) && failureCount < 1,
  });
}
