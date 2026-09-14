import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { getVoiceModels, selectVoiceModels, type VoiceTarget } from '~/api/voice';
import { useOptionalStandaloneChatContext } from '~/pages/standaloneChat/StandaloneChatContext';
import { QueryKeys } from '~/types/chat/keys';

export function useVoiceTarget(): VoiceTarget {
  const standalone = useOptionalStandaloneChatContext();
  const isGuest = standalone?.mode === 'guest';
  const flowId = standalone?.flowId ?? '';
  return useMemo(
    () => isGuest ? { version: 'v3', flowId } : { version: 'v1' },
    [isGuest, flowId],
  );
}

export function useVoiceModels() {
  const target = useVoiceTarget();
  return useQuery({
    queryKey: target.version === 'v3'
      ? ['publishedVoiceModels', target.flowId]
      : [QueryKeys.getWorkspaceModel],
    queryFn: () => getVoiceModels(target),
    select: selectVoiceModels,
    enabled: target.version === 'v1' || !!target.flowId,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}
