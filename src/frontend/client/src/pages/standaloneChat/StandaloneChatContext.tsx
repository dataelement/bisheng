import { createContext, useContext } from 'react';

export interface StandaloneChatContextValue {
  mode: 'guest' | 'auth';
  flowType: 'workflow' | 'assistant';
  flowId: string;
  apiVersion: 'v1' | 'v2' | 'v3';
  autoRerunOnOpen: boolean;
}

export function resolveStandaloneApiVersion(mode: StandaloneChatContextValue['mode']): 'v1' | 'v3' {
  return mode === 'guest' ? 'v3' : 'v1';
}

export const StandaloneChatContext = createContext<StandaloneChatContextValue | null>(null);

export function useStandaloneChatContext() {
  const ctx = useContext(StandaloneChatContext);
  if (!ctx) {
    throw new Error('useStandaloneChatContext must be used within StandaloneChatContext.Provider');
  }
  return ctx;
}

export function useOptionalStandaloneChatContext() {
  return useContext(StandaloneChatContext);
}
