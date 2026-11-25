/**
 * F004 — the `ask_user` tool call of a run once the user answered it. Pure.
 */
import type { RunAskUserAnsweredData, RunAskUserData } from './runEventTypes';
import type { RunState, RunToolCall } from './runStore';

/** Name of the tool call that asks the user a question. */
export const ASK_USER_TOOL_NAME = 'ask_user';

function askUserCallIndex(toolCalls: RunToolCall[], callId: string): number {
    if (callId) {
        const idx = toolCalls.findIndex((t) => t.callId === callId);
        if (idx !== -1) return idx;
    }
    for (let i = toolCalls.length - 1; i >= 0; i -= 1) {
        if (toolCalls[i].name === ASK_USER_TOOL_NAME && toolCalls[i].status === 'running') return i;
    }
    return -1;
}

/**
 * Tool calls when the run asks: the `ask_user` call takes the question as
 * `params`. The call keeps it after the send of the answer clears
 * `pendingQuestion`, which happens before `ask_user_answered` arrives. A call
 * the page never saw (it joined after a resync) is added, still running.
 */
export function askAskUserCall(run: RunState, question: RunAskUserData | null | undefined): RunToolCall[] {
    if (!question) return run.toolCalls;
    const idx = askUserCallIndex(run.toolCalls, question.call_id || '');
    const prev = idx === -1 ? null : run.toolCalls[idx];
    const asked: RunToolCall = {
        callId: prev?.callId || question.call_id || '',
        name: ASK_USER_TOOL_NAME,
        status: 'running',
        stepType: prev?.stepType ?? 'tool',
        callReason: prev?.callReason ?? '',
        params: question,
        output: null,
        extraInfo: prev?.extraInfo ?? {},
        order: prev?.order ?? run.thinking.length + run.toolCalls.length,
    };
    return idx === -1 ? [...run.toolCalls, asked] : run.toolCalls.map((t, i) => (i === idx ? asked : t));
}

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
    const idx = askUserCallIndex(run.toolCalls, callId);
    const prev = idx === -1 ? null : run.toolCalls[idx];
    if (!prev && !run.pendingQuestion) return run.toolCalls;
    const answer = data?.answer;
    const answered: RunToolCall = {
        callId: prev?.callId || callId,
        name: ASK_USER_TOOL_NAME,
        status: 'done',
        stepType: prev?.stepType ?? 'tool',
        callReason: prev?.callReason ?? '',
        params: prev?.params ?? run.pendingQuestion ?? null,
        output: typeof answer === 'string' ? answer : answer == null ? '' : JSON.stringify(answer),
        extraInfo: prev?.extraInfo ?? {},
        order: prev?.order ?? run.thinking.length + run.toolCalls.length,
    };
    return idx === -1 ? [...run.toolCalls, answered] : run.toolCalls.map((t, i) => (i === idx ? answered : t));
}
