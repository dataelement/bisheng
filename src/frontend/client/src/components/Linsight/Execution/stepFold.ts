/**
 * Ingest-time folding of `task_execute_step` frames.
 *
 * The backend streams thinking as one frame per token delta, all sharing one
 * call_id, and a tool call as a start frame plus an end frame. Appending every
 * frame to the store made `history` grow with the TOKEN count (thousands to tens
 * of thousands of entries per task), and every render re-merged the whole log —
 * per-frame cost linear in frames, total cost quadratic.
 *
 * appendStepFrame folds a frame into the existing entry with the same call_id
 * instead, so `history` grows with the STEP count. This is the same shape the
 * backend persists (state_message_manager upserts by call_id), so a live log and
 * a reloaded one now have the same structure.
 *
 * Contract: for any frame sequence F,
 *   mergeStepFrames(fold(F)) equals mergeStepFrames(F)
 * on every MergedStep field the renderer reads (see stepFold.test.ts). The
 * folded entry carries `client_started_at` so the first frame's timestamp
 * survives the fold (mergeStepFrames reads it as startedAt).
 */
import type { ExecStepEventData } from './execTypes';

/** Frames mergeStepFrames drops by name; never fold into or out of them. */
function isDroppedFrame(frame: ExecStepEventData): boolean {
    return frame.name === 'ask_user' || frame.name === 'ls';
}

function hasKeys(obj: Record<string, unknown> | null | undefined): boolean {
    return !!obj && Object.keys(obj).length > 0;
}

/**
 * Fold `next` into `prev` (same call_id). Mirrors the per-field rules of the
 * "later frame for the same call" branch in mergeStepFrames:
 * identity fields (task_id / name / step_type / call_reason / namespace) stay
 * from the first frame, `params` takes the latest non-empty one, `output`
 * follows the same append rule, `extra_info` is spread-merged, and the step is
 * closed once any frame is an end frame.
 */
export function foldStepFrame(prev: ExecStepEventData, next: ExecStepEventData): ExecStepEventData {
    const prevOutput = prev.output || '';
    let output = prevOutput;
    if (next.output) {
        output = prevOutput && next.output !== prevOutput ? prevOutput + next.output : next.output;
    }
    const prevTs = typeof prev.timestamp === 'number' ? prev.timestamp : undefined;
    const nextTs = typeof next.timestamp === 'number' ? next.timestamp : undefined;
    const prevStart = typeof prev.client_started_at === 'number' ? prev.client_started_at : prevTs;
    return {
        ...next,
        task_id: prev.task_id,
        name: prev.name,
        step_type: prev.step_type,
        call_reason: prev.call_reason,
        namespace: prev.namespace,
        status: prev.status === 'end' || next.status === 'end' ? 'end' : next.status,
        params: hasKeys(next.params) ? next.params : prev.params,
        output,
        extra_info: next.extra_info ? { ...(prev.extra_info || {}), ...next.extra_info } : prev.extra_info,
        timestamp: nextTs ?? prevTs,
        client_started_at: prevStart ?? nextTs,
    };
}

/**
 * Return a new history with `frame` applied: folded into the entry that shares
 * its call_id (kept at that entry's position, i.e. first-seen order), or
 * appended when no such entry exists. Never mutates `history`.
 *
 * Generic over the entry type so a caller keeps its own element type (the
 * store declares its own shape for task history entries).
 */
export function appendStepFrame<T extends ExecStepEventData>(
    history: readonly T[] | null | undefined,
    frame: T,
): T[] {
    const list = history || [];
    const callId = frame?.call_id;
    if (!callId || isDroppedFrame(frame)) return [...list, frame];
    // The matching entry is almost always the last one (a thinking passage, or a
    // tool whose end frame follows its start), so scan from the tail.
    for (let i = list.length - 1; i >= 0; i--) {
        const entry = list[i];
        if (!entry || entry.call_id !== callId || isDroppedFrame(entry)) continue;
        const out = list.slice();
        // The fold spreads `frame` (a T) and only overrides ExecStepEventData
        // fields, so the result keeps T's shape.
        out[i] = foldStepFrame(entry, frame) as T;
        return out;
    }
    return [...list, frame];
}
