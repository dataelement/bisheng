import { create } from 'zustand';
import type { AuthSessionMetadata } from '@bisheng/api-client';

interface AuthSessionState {
  phase: 'loading' | 'ready' | 'unavailable' | 'host';
  session: AuthSessionMetadata | null;
}
/** Presentation only; all network and credential handling belongs to the API controller. */
export const useAuthSessionStore = create<AuthSessionState>(() => ({ phase: 'loading', session: null }));
