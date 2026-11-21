/**
 * F004 — selectors of the run store; re-exported by `runStore`.
 */
import { planProgressOf, type PlanProgress } from './runPlanProgress';
import type { ConversationRunState, RunState, RunStoreState } from './runStore';

export const selectConversationRun =
    (conversationId: string) =>
    (state: RunStoreState): ConversationRunState | undefined =>
        state.conversations[conversationId];

export const selectRun =
    (conversationId: string) =>
    (state: RunStoreState): RunState | null =>
        state.conversations[conversationId]?.run ?? null;

/** True from `run_started` until a terminal event, including while waiting for an answer. */
export const selectIsRunning =
    (conversationId: string) =>
    (state: RunStoreState): boolean => {
        const status = state.conversations[conversationId]?.run?.status;
        return status === 'running' || status === 'waiting';
    };

/**
 * Sending is accepted in every state (AC-12): idle starts a run, a running run
 * takes the message as a steer, a waiting run takes it as the answer.
 */
export const selectCanSend: (conversationId: string) => (state: RunStoreState) => boolean = () => () => true;

export const selectPlanProgress =
    (conversationId: string) =>
    (state: RunStoreState): PlanProgress =>
        planProgressOf(state.conversations[conversationId]?.run?.plan);

export const selectIsMessageQueued =
    (conversationId: string, messageId: string | number | null | undefined) =>
    (state: RunStoreState): boolean =>
        messageId !== null &&
        messageId !== undefined &&
        Boolean(state.conversations[conversationId]?.queuedMessages[String(messageId)]);

export const selectLastEventId =
    (conversationId: string) =>
    (state: RunStoreState): string | null =>
        state.conversations[conversationId]?.lastEventId ?? null;
