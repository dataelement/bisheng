/**
 * F004 — an answered `ask_user` call of a daily answer as the step data
 * IntentRow reads. Pure.
 */
import type { AgentEvent } from '~/api/chatApi';
import { runQuestionToClarifyData } from '~/components/Linsight/Execution/clarify';
import type { ExecStepEventData } from '~/components/Linsight/Execution/execTypes';
import type { RunAskUserData } from '~/store/runEventTypes';

export type ToolCallEvent = Extract<AgentEvent, { type: 'tool_call' }>;

/** The question (`args`, the run's `ask_user` event) and the answer (`results`). */
export function askedQuestionData(event: ToolCallEvent): ExecStepEventData {
    const args = (event.args ?? {}) as Partial<RunAskUserData>;
    const question: RunAskUserData = {
        call_id: args.call_id || event.tool_call_id,
        reason: typeof args.reason === 'string' ? args.reason : '',
        questions: Array.isArray(args.questions) ? args.questions : [],
    };
    const answer = event.results;
    return {
        ...runQuestionToClarifyData(question),
        user_input: typeof answer === 'string' ? answer : answer == null ? '' : JSON.stringify(answer),
    };
}
