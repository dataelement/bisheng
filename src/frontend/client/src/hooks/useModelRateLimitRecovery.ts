import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { v4 } from 'uuid';
import {
  recoverModelCall,
  type ModelRecoveryAction,
  type ModelRecoveryResponse,
  type ModelRecoveryTarget,
} from '~/api/modelRecovery';
import { QueryKeys } from '~/types/chat';

interface RecoveryRunResult {
  accepted: boolean;
  attemptId: string;
}

interface RateLimitRecoveryMessage {
  errorType?: string;
  unfinished?: boolean;
}

export function closeSupersededRateLimitRecoveries<T extends RateLimitRecoveryMessage>(
  messages: T[],
): T[] {
  let changed = false;
  const next = messages.map((message) => {
    if (message.errorType !== 'rate_limit' || message.unfinished !== true) return message;
    changed = true;
    return { ...message, unfinished: false };
  });
  return changed ? next : messages;
}

interface RecoveryAttemptController {
  run: (request: (attemptId: string) => Promise<unknown>) => Promise<RecoveryRunResult>;
  isActiveAttempt: (attemptId?: string | null) => boolean;
  setActiveAttempt: (attemptId: string | null) => void;
  getActiveAttempt: () => string | null;
}

export function createRecoveryAttemptController(
  createAttemptId: () => string,
): RecoveryAttemptController {
  let activeAttemptId: string | null = null;
  let pending = false;

  return {
    async run(request) {
      if (pending) {
        return { accepted: false, attemptId: activeAttemptId ?? '' };
      }
      const attemptId = createAttemptId();
      activeAttemptId = attemptId;
      pending = true;
      try {
        await request(attemptId);
        return { accepted: true, attemptId };
      } finally {
        pending = false;
      }
    },
    isActiveAttempt(attemptId) {
      return !!attemptId && attemptId === activeAttemptId;
    },
    setActiveAttempt(attemptId) {
      activeAttemptId = attemptId;
    },
    getActiveAttempt() {
      return activeAttemptId;
    },
  };
}

export interface UseModelRateLimitRecoveryOptions {
  target: ModelRecoveryTarget;
  executionId?: string | null;
  subjectId?: string | null;
  activeAttemptId?: string | null;
  currentModelId?: string | number | null;
  transport?: typeof recoverModelCall;
}

export interface RunModelRecoveryOptions {
  action: ModelRecoveryAction;
  targetModelId?: string | number;
}

export function buildManualRetryOptions(
  currentModelId?: string | number | null,
): RunModelRecoveryOptions {
  return {
    action: 'manual_retry',
    targetModelId: currentModelId ?? undefined,
  };
}

export function nextManualRetryCount(
  currentCount: number,
  action: ModelRecoveryAction,
  errorType?: string,
): number {
  return action === 'manual_retry' && errorType === 'rate_limit'
    ? currentCount + 1
    : 0;
}

export function shouldRecommendModelSwitch(manualRetryCount: number): boolean {
  return manualRetryCount >= 3;
}

export function shouldOpenModelSwitchRecommendation({
  errorType,
  pending,
  recommended,
  eventAttemptId,
  activeAttemptId,
}: {
  errorType?: string | null;
  pending: boolean;
  recommended: boolean;
  eventAttemptId?: string | null;
  activeAttemptId?: string | null;
}): boolean {
  return errorType === 'rate_limit'
    && !pending
    && recommended
    && !!eventAttemptId
    && eventAttemptId === activeAttemptId;
}

export function useModelRateLimitRecovery({
  target,
  executionId,
  subjectId,
  activeAttemptId,
  currentModelId,
  transport = recoverModelCall,
}: UseModelRateLimitRecoveryOptions) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [lastResponse, setLastResponse] = useState<ModelRecoveryResponse | null>(null);
  const [manualRetryCount, setManualRetryCount] = useState(0);
  const attemptRef = useRef<string | null>(activeAttemptId ?? null);
  const externalAttemptRef = useRef<string | null>(activeAttemptId ?? null);
  const pendingRef = useRef(false);
  if (activeAttemptId && activeAttemptId !== externalAttemptRef.current) {
    externalAttemptRef.current = activeAttemptId;
    attemptRef.current = activeAttemptId;
  }

  const recover = useCallback(async ({ action, targetModelId }: RunModelRecoveryOptions) => {
    if (!executionId || !subjectId || pendingRef.current) return null;

    const attemptId = v4();
    attemptRef.current = attemptId;
    pendingRef.current = true;
    setPending(true);
    if (action === 'switch_model') setManualRetryCount(0);
    try {
      const response = await transport(target, {
        executionId,
        attemptId,
        subjectId,
        action,
        targetModelId,
      });
      setLastResponse(response);
      setManualRetryCount((count) => nextManualRetryCount(
        count,
        action,
        response.error_type,
      ));
      await queryClient.invalidateQueries([QueryKeys.bishengConfig]);
      return response;
    } catch (error) {
      setManualRetryCount(0);
      throw error;
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }, [executionId, queryClient, subjectId, target, transport]);

  const isActiveAttempt = useCallback(
    (attemptId?: string | null) => !!attemptId && attemptId === attemptRef.current,
    [],
  );
  const resetManualRetryCount = useCallback(() => setManualRetryCount(0), []);

  return {
    pending,
    activeAttemptId: attemptRef.current,
    lastResponse,
    manualRetryCount,
    showSwitchRecommendation: shouldRecommendModelSwitch(manualRetryCount),
    resetManualRetryCount,
    recover,
    retry: () => recover(buildManualRetryOptions(currentModelId)),
    switchModel: (targetModelId: string | number) => recover({
      action: 'switch_model',
      targetModelId,
    }),
    isActiveAttempt,
  };
}
