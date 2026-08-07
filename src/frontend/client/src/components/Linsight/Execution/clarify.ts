/**
 * Clarify (user_input) parsing and answer composition. Split out of stepUtils.ts.
 */
import type { ExecStepEventData } from './execTypes';

// ── clarify / user_input parsing ─────────────────────────────────────────────

/**
 * Sent verbatim as `user_input` when the user taps 跳过，开始任务 on the fallback
 * clarify card (ClarifyFallbackCard). A fixed Chinese control instruction (NOT
 * localized) so (a) the multilingual agent reliably proceeds with default
 * assumptions and (b) IntentRow can detect "skipped" by exact match regardless of
 * UI locale. The backend resumes opaquely (Command(resume=user_input)).
 */
export const CLARIFY_SKIP_SIGNAL = '跳过澄清，请基于合理的默认假设直接开始执行任务。';

/** One question page parsed from `user_input.data.params.tool_calls[].args`. */
export interface ClarifyQuestion {
    id: string;
    question: string;
    options: string[];
    multiple: boolean;
}

/** Parsed clarify request; `questions` empty => fall back to a plain textarea. */
export interface ClarifyRequest {
    taskId: string;
    callReason: string;
    questions: ClarifyQuestion[];
    raw: ExecStepEventData;
}

/**
 * Defensive parse of a `user_input` event payload (fixture shape:
 * data.params.tool_calls[{id, name, args:{question, options}}]). Anything
 * unparseable degrades to a free-text question (legacy UserInput shape).
 */
export function parseClarifyRequest(data: ExecStepEventData): ClarifyRequest {
    const callReason = data.call_reason || data.params?.call_title || '';
    const toolCalls = Array.isArray(data.params?.tool_calls) ? data.params!.tool_calls : [];

    const questions: ClarifyQuestion[] = [];
    toolCalls.forEach((tc: any, idx: number) => {
        const args = tc?.args || {};
        const question = typeof args.question === 'string' ? args.question : typeof args.title === 'string' ? args.title : '';
        if (!question) return;
        // Options are plain strings. Checkpoints parked before the is_default
        // feature was removed may still carry {text, ...} objects, so extract the
        // text defensively; the text is both the display label and answer value.
        const rawOptions = Array.isArray(args.options) ? args.options : [];
        const options: string[] = [];
        rawOptions.forEach((o: any) => {
            if (typeof o === 'string') {
                options.push(o);
            } else if (o && typeof o === 'object' && typeof o.text === 'string') {
                options.push(o.text);
            }
        });
        questions.push({
            id: String(tc?.id || `q_${idx}`),
            question,
            options,
            multiple: !!(args.multiple || args.multi_select || args.type === 'multi'),
        });
    });

    // legacy interrupt shape (params.call_title / call_content) => single free-text question
    if (!questions.length && data.params?.call_content) {
        questions.push({ id: 'q_legacy', question: String(data.params.call_content), options: [], multiple: false });
    }

    return { taskId: data.task_id || '', callReason, questions, raw: data };
}

/** Compose the structured answer text submitted through user-input API. */
export function composeClarifyAnswer(
    questions: ClarifyQuestion[],
    answers: Record<string, string[]>,
    skippedText: string,
): string {
    if (!questions.length) return answers.__free__?.join('') || '';
    return questions
        .map((q) => {
            const ans = answers[q.id];
            const text = ans && ans.length ? ans.join('、') : skippedText;
            return questions.length > 1 ? `${q.question}: ${text}` : text;
        })
        .join('\n');
}

/**
 * The newest UNANSWERED clarify (call_user_input) across a turn's session steps +
 * tasks (and legacy subtask children), or null when nothing is pending. This is
 * the precise "parked on an ask_user, waiting for the user's reply" signal: the
 * live WS keeps the top-level session status at Running during a park (park is
 * NOT a distinct live status — see reference notes), so an unanswered
 * call_user_input is what distinguishes "waiting for your reply" from "actively
 * executing". Shared by every carrier (ExecutionFlow / TaskTurnPanel / ChatView)
 * so the timeline clock freeze + the input's stop/await state stay in lockstep.
 */
export function findPendingUserInput(
    sessionSteps: ExecStepEventData[] | null | undefined,
    tasks: ReadonlyArray<{
        history?: ExecStepEventData[] | null;
        children?: ReadonlyArray<{ history?: ExecStepEventData[] | null }> | null;
    }> | null | undefined,
): ExecStepEventData | null {
    const entries: ExecStepEventData[] = [];
    (sessionSteps || []).forEach((s) => s?.step_type === 'call_user_input' && entries.push(s));
    (tasks || []).forEach((task) => {
        (task.history || []).forEach((h) => h?.step_type === 'call_user_input' && entries.push(h));
        (task.children || []).forEach((child) =>
            (child.history || []).forEach((h) => h?.step_type === 'call_user_input' && entries.push(h)),
        );
    });
    return [...entries].reverse().find((e) => !e.is_completed) || null;
}
