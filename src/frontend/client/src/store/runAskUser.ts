/**
 * F004 — the `ask_user` tool call of a run once the user answered it. Pure.
 */
import type { RunAskUserAnsweredData } from './runEventTypes';
import type { RunState, RunToolCall } from './runStore';

/** Name of the tool call that asks the user a question. */
export const ASK_USER_TOOL_NAME = 'ask_user';

/**
 * Tool calls after the user answered the pending question. The `ask_user` call
 * gets no end frame (the run parked on it), so the answer closes it: it keeps
 * the question as `params` and the answer as `output`, as the stored answer
 * row has it. A call the page never saw (it joined after a resync) is added.
 */
export function answerAskUserCall(
    run: RunState,
    data: RunAskUserAnsweredData | undefined,
): RunToolCall[] {
    const callId = data?.call_id || run.pendingQuestion?.call_id || '';
    let idx = callId ? run.toolCalls.findIndex((t) => t.callId === callId) : -1;
    if (idx === -1) {
        for (let i = run.toolCalls.length - 1; i >= 0; i -= 1) {
            const t = run.toolCalls[i];
            if (t.name === ASK_USER_TOOL_NAME && t.status === 'running') {
                idx = i;
                break;
            }
        }
    }
    const prev = idx === -1 ? null : run.toolCalls[idx];
    if (!prev && !run.pendingQuestion) return run.toolCalls;
    const answer = data?.answer;
    const answered: RunToolCall = {
        callId: prev?.callId || callId,
        name: ASK_USER_TOOL_NAME,
        status: 'done',
        stepType: prev?.stepType ?? 'tool',
        callReason: prev?.callReason ?? '',
        params: run.pendingQuestion ?? prev?.params ?? null,
        output: typeof answer === 'string' ? answer : answer == null ? '' : JSON.stringify(answer),
        extraInfo: prev?.extraInfo ?? {},
        order: prev?.order ?? run.thinking.length + run.toolCalls.length,
    };
    return idx === -1 ? [...run.toolCalls, answered] : run.toolCalls.map((t, i) => (i === idx ? answered : t));
}
