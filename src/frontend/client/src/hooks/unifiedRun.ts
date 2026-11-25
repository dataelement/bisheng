/**
 * F004 (T047) — pure helpers that connect the run store to the message list
 * of the conversation page. No React, no HTTP.
 *
 * The answer of a run in progress is one local row of the message list, marked
 * with `liveRunId`. While the mark is there the row shows what the run store
 * holds for that run. When the run ends the row is frozen (mark removed) and
 * the history endpoint then replaces the whole list, so the persisted answer
 * takes the place of the live one and is never shown next to it.
 */
import type { ChatMessage } from '~/api/chatApi';
import type { RunSendResult, RunState } from '~/store/runStore';
import { isUmbrellaFailureCode, parseFailureInfo } from '~/utils/failureInfo';
import { agentEventsOfRun } from './runAgentEvents';

export { agentEventsOfRun };

// ---------------------------------------------------------------------------
// Send response
// ---------------------------------------------------------------------------

export type SendOutcome =
    /** A run started, or the message answered the pending question of `run_id`. */
    | { kind: 'started'; result: RunSendResult }
    /** The message waits in the inbox of the running (or relay) run. */
    | { kind: 'queued'; result: RunSendResult }
    /**
     * The backend answered with today's SSE text although protocol 2 was asked
     * for (a blocked input is recorded as a normal turn, no run starts).
     */
    | { kind: 'legacy'; conversationId: string | null; error: { code?: number; message?: string } | null }
    /** The input was blocked by content safety: the turn is stored, no run starts (design §7 item 3). */
    | { kind: 'blocked'; blocked: BlockedSend }
    | { kind: 'invalid' };

/** Answer of a send whose input content safety blocked (`disposition: "blocked"`). */
export interface BlockedSend {
    conversationId: string;
    /** The reply the backend stored as the answer of the turn. */
    autoReply: string;
    /** Row ids of the stored question and answer; '' when the backend named none. */
    questionMessageId: string;
    answerMessageId: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** Read the conversation id and a possible error out of legacy SSE text. */
export function parseLegacySendFrames(text: string): {
    conversationId: string | null;
    error: { code?: number; message?: string } | null;
} {
    let conversationId: string | null = null;
    let error: { code?: number; message?: string } | null = null;
    for (const block of text.split(/\r?\n\r?\n/)) {
        const lines = block.split(/\r?\n/);
        const isErrorEvent = lines.some((line) => /^event:\s*error\s*$/.test(line));
        const dataText = lines
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).trim())
            .join('\n');
        if (!dataText) continue;
        let data: Record<string, unknown> | null = null;
        try {
            data = asRecord(JSON.parse(dataText));
        } catch {
            data = null;
        }
        if (!data) continue;
        if (isErrorEvent) {
            error = {
                code: typeof data.status_code === 'number' ? data.status_code : undefined,
                message: typeof data.status_message === 'string' ? data.status_message : undefined,
            };
            continue;
        }
        const found =
            asRecord(data.conversation)?.conversationId ?? asRecord(data.message)?.conversationId ?? data.chat_id;
        if (typeof found === 'string' && found) conversationId = found;
    }
    return { conversationId, error };
}

/** Sort the body of a protocol-2 send into the cases the page handles. */
export function classifySendResponse(raw: unknown): SendOutcome {
    if (typeof raw === 'string') {
        return { kind: 'legacy', ...parseLegacySendFrames(raw) };
    }
    const envelope = asRecord(raw);
    const data = asRecord(envelope?.data) ?? envelope;
    if (data?.disposition === 'blocked') {
        if (typeof data.conversation_id !== 'string' || !data.conversation_id) return { kind: 'invalid' };
        return {
            kind: 'blocked',
            blocked: {
                conversationId: data.conversation_id,
                autoReply: typeof data.auto_reply === 'string' ? data.auto_reply : '',
                questionMessageId: data.question_message_id == null ? '' : String(data.question_message_id),
                answerMessageId: data.answer_message_id == null ? '' : String(data.answer_message_id),
            },
        };
    }
    if (!data || typeof data.run_id !== 'string' || typeof data.disposition !== 'string') return { kind: 'invalid' };
    const result: RunSendResult = {
        run_id: data.run_id,
        disposition: data.disposition,
        message_id: data.message_id == null ? '' : String(data.message_id),
        ...(typeof data.conversation_id === 'string' && data.conversation_id
            ? { conversation_id: data.conversation_id }
            : {}),
    };
    if (result.disposition === 'started') return { kind: 'started', result };
    if (result.disposition === 'queued') return { kind: 'queued', result };
    return { kind: 'invalid' };
}

/** True when a `started` answer continues the run that was waiting for the user. */
export function isAnswerToPendingQuestion(run: RunState | null | undefined, result: RunSendResult): boolean {
    return !!run && run.status === 'waiting' && run.runId === result.run_id && result.disposition === 'started';
}

/**
 * True while the run waits for the user's answer to a question. The next
 * message of the conversation is then the answer: it continues the same run
 * and is not a new deep-research request.
 */
export function isRunAwaitingAnswer(run: RunState | null | undefined): boolean {
    return run?.status === 'waiting' && !!run.pendingQuestion;
}

// ---------------------------------------------------------------------------
// Live row
// ---------------------------------------------------------------------------

export function isRunActive(run: RunState | null | undefined): boolean {
    return run?.status === 'running' || run?.status === 'waiting';
}

/** The fields of the answer row that come from the run. */
export function liveFieldsOfRun(run: RunState): Partial<ChatMessage> {
    const events = agentEventsOfRun(run);
    const hasContent = !!run.text || events.length > 0;
    return {
        text: run.text,
        ...(hasContent ? { category: 'agent_answer', events } : {}),
    };
}

/**
 * Failure fields of the answer row of a failed run, the same ones the history
 * gives for the stored row. `errorText` is the localized copy of the code; the
 * copy of an umbrella code (11090 / 11091) is deep-research wording and says
 * nothing a user can act on, so the card's own copy per type is used instead.
 */
export function failureFieldsOfRun(run: RunState, errorText: string): Partial<ChatMessage> {
    if (run.status !== 'failed') return {};
    const error = run.error;
    const failureInfo = parseFailureInfo(error?.failure_info);
    return {
        error: true,
        errorText: isUmbrellaFailureCode(error?.code) ? '' : errorText,
        ...(failureInfo ? { failureInfo } : {}),
        ...(error?.code != null ? { errorCode: error.code } : {}),
        ...(error?.reason ? { errorType: error.reason } : {}),
        ...(error?.detail ? { errorDetail: error.detail } : {}),
        ...(error?.reference_id ? { referenceId: error.reference_id } : {}),
    };
}

/**
 * What the stored row of a stopped run keeps for a tool call that was still
 * running (backend `run_projector_direct.STOPPED_TOOL_NOTE`). Not a failure.
 */
export const STOPPED_TOOL_NOTE = 'stopped by user';

/**
 * Fields of the answer row of a run the user stopped: the content so far, the
 * neutral "stopped" mark, and tool calls that were running shown as stopped.
 */
export function stoppedFieldsOfRun(run: RunState): Partial<ChatMessage> {
    if (run.status !== 'stopped') return {};
    const events = agentEventsOfRun(run).map((event) =>
        event.type === 'tool_call' && event.inflight ? { ...event, inflight: false, error: STOPPED_TOOL_NOTE } : event,
    );
    return { stopped: true, ...(events.length ? { events } : {}) };
}

/**
 * Marks the unified runtime stores in a history row's `extra`: a stopped
 * answer (`status: "stopped"`, no `error`), the inbox id of a message sent
 * into a run (`steer_message_id`) and whether that message still waits in the
 * inbox (`queued`; the backend removes it when the run reads the message),
 * and the question a message answered (`ask_user`; the answer row shows it).
 */
export function runRowMarks(extra: unknown): Partial<ChatMessage> {
    const record = asRecord(extra);
    if (!record) return {};
    const steerId = record.steer_message_id;
    return {
        ...(record.status === 'stopped' && !record.error ? { stopped: true } : {}),
        ...(asRecord(record.ask_user) ? { answersQuestion: true } : {}),
        ...(typeof steerId === 'string' && steerId
            ? { steerMessageId: steerId, steerQueued: record.queued === true }
            : {}),
    };
}

/** Id the run store knows a user row by: its inbox id when it was sent into a run. */
export function queueIdOf(row: Pick<ChatMessage, 'messageId' | 'steerMessageId'>): string {
    return row.steerMessageId || String(row.messageId);
}

function newLiveRow(runId: string, parent: ChatMessage | undefined, sender: string): ChatMessage {
    return {
        text: '',
        sender,
        isCreatedByUser: false,
        parentMessageId: parent?.messageId ?? '',
        conversationId: parent?.conversationId ?? '',
        messageId: `run:${runId}`,
        error: false,
        liveRunId: runId,
    };
}

/** The message list as rendered: the live row shows the current state of its run. */
export function withLiveRun(messages: ChatMessage[], run: RunState | null | undefined): ChatMessage[] {
    if (!run) return messages;
    const index = messages.findIndex((m) => m.liveRunId === run.runId);
    if (index === -1) return messages;
    const next = messages.slice();
    next[index] = { ...messages[index], ...liveFieldsOfRun(run), ...keepTaskCategory(messages[index]) };
    return next;
}

// ---------------------------------------------------------------------------
// Stored deep-research row of a run in progress (T061)
// ---------------------------------------------------------------------------

/**
 * A deep-research turn is stored from its start as a `task` row that points at
 * its run record (`linsightSessionVersionId`). The row keeps that category
 * while it shows the run, so the page still knows which run record the turn
 * belongs to (workspace panel, pinned plan).
 */
function keepTaskCategory(row: ChatMessage): Partial<ChatMessage> {
    return row.category === 'task' && row.linsightSessionVersionId ? { category: 'task' } : {};
}

/** Statuses of a run record (`linsight_session_version.status`) that mean "not ended". */
const VERSION_IN_PROGRESS_STATUSES: ReadonlySet<string> = new Set([
    'not_started',
    'in_progress',
    'waiting_for_user_input',
]);

export function isVersionInProgress(status: unknown): boolean {
    return typeof status === 'string' && VERSION_IN_PROGRESS_STATUSES.has(status);
}

export interface LiveTaskRowCandidate {
    index: number;
    versionId: string;
}

/**
 * The stored deep-research row that may belong to the run in progress: the
 * last answer row of the list, when it is a `task` row and only user rows
 * follow it (messages sent into the run). Whether its run record is really the
 * one still going is not in the list; the caller asks the run record.
 * Returns null when the run already has a row, or a send is waiting for its run id.
 */
export function liveTaskRowCandidate(
    messages: ChatMessage[],
    run: RunState | null | undefined,
): LiveTaskRowCandidate | null {
    if (!run || !isRunActive(run)) return null;
    if (messages.some((m) => m.liveRunId === run.runId || m.liveRunId === '')) return null;
    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const row = messages[index];
        if (row.isCreatedByUser) continue;
        if (row.category !== 'task' || !row.linsightSessionVersionId || row.liveRunId !== undefined) return null;
        return { index, versionId: row.linsightSessionVersionId };
    }
    return null;
}

/** Make the stored `task` row of `versionId` the live row of `runId`. */
export function bindLiveTaskRow(messages: ChatMessage[], versionId: string, runId: string): ChatMessage[] {
    if (!versionId || !runId || messages.some((m) => m.liveRunId === runId)) return messages;
    const index = messages.findIndex(
        (m) => !m.isCreatedByUser && m.category === 'task' && m.linsightSessionVersionId === versionId,
    );
    if (index === -1) return messages;
    const next = messages.slice();
    next[index] = { ...messages[index], liveRunId: runId };
    return next;
}

/**
 * Whether a live row has to be added for a run this page did not start
 * (the page was opened while the run was going, or a relay run took the
 * queued messages). It is added only when the list ends with a user message:
 * a trailing answer row means the turn already has its row (a deep-research
 * turn is stored from the start, a legacy stream owns its placeholder).
 *
 * The caller asks this once per run, when the run is first seen: a message
 * sent later into the same run also ends the list with a user row.
 */
export function needsLiveRow(messages: ChatMessage[], run: RunState | null | undefined): boolean {
    if (!run || !isRunActive(run)) return false;
    if (messages.some((m) => m.liveRunId === run.runId || m.liveRunId === '')) return false;
    const last = messages[messages.length - 1];
    return !!last && !!last.isCreatedByUser;
}

export function addLiveRow(messages: ChatMessage[], run: RunState, sender: string): ChatMessage[] {
    if (!needsLiveRow(messages, run)) return messages;
    return [...messages, newLiveRow(run.runId, messages[messages.length - 1], sender)];
}

/**
 * State to freeze the row of a run another run took the place of. The backend
 * starts a run only after the previous one ended, so a replaced run that still
 * reads as active here ended without this page seeing its terminal event: it
 * counts as finished and none of its tool calls is still running.
 */
export function settleReplacedRun(run: RunState): RunState {
    if (!isRunActive(run)) return run;
    return {
        ...run,
        status: 'finished',
        pendingQuestion: null,
        queuePosition: null,
        toolCalls: run.toolCalls.map((call) => (call.status === 'running' ? { ...call, status: 'done' } : call)),
    };
}

/** Whether the list holds the live row of this run. */
export function hasLiveRow(messages: ChatMessage[], runId: string): boolean {
    return messages.some((m) => m.liveRunId === runId);
}

/**
 * Files of the stored answer of an ended run, with the row's ids (design §7
 * item 11): the file cards of a finished answer fetch the answer's own copy,
 * not the workspace file a later run may overwrite. Empty when the terminal
 * event named none; the history reload then brings the row's files.
 */
export function answerFileFieldsOfRun(run: RunState): Partial<ChatMessage> {
    return run.answerFiles?.length ? { files: run.answerFiles } : {};
}

/**
 * Turn the live row of an ended run into a plain row holding the final state.
 * It stays on screen until the history endpoint returns the persisted turn.
 */
export function freezeLiveRun(messages: ChatMessage[], run: RunState, errorText = ''): ChatMessage[] {
    const index = messages.findIndex((m) => m.liveRunId === run.runId);
    if (index === -1) return messages;
    const row = { ...messages[index] };
    delete row.liveRunId;
    const next = messages.slice();
    next[index] = {
        ...row,
        ...liveFieldsOfRun(run),
        ...keepTaskCategory(row),
        ...failureFieldsOfRun(run, errorText),
        ...stoppedFieldsOfRun(run),
        ...answerFileFieldsOfRun(run),
    };
    return next;
}

/**
 * Give an ended run that never had a row its final row. Used when a relay run
 * fails before the page saw it running: its start and its failure arrive
 * together, so no live row was created to carry the failure.
 */
export function addEndedRunRow(messages: ChatMessage[], run: RunState, sender: string, errorText = ''): ChatMessage[] {
    if (isRunActive(run) || messages.some((m) => m.liveRunId === run.runId || m.messageId === `run:${run.runId}`)) {
        return messages;
    }
    const row = newLiveRow(run.runId, messages[messages.length - 1], sender);
    return freezeLiveRun([...messages, row], run, errorText);
}

// ---------------------------------------------------------------------------
// Message list after a send
// ---------------------------------------------------------------------------

export interface SentMessageRefs {
    /** Client id of the optimistic user row. */
    userMessageId: string;
    /** Display name for a live row that has to be created. */
    sender: string;
    /**
     * The store already showed `run_id` as its current run before this send
     * (the message answered its pending question). Such a run has its row, or
     * was deliberately left without one, so none is created here.
     */
    runKnown?: boolean;
    /**
     * The message answered the question the run was waiting on. Its row leaves
     * the list: the answer row shows the question with this answer, as the
     * history does (the stored row of an answer is not listed).
     */
    answered?: boolean;
}

/**
 * Apply the answer of a send to the optimistic rows.
 *
 * - `started`: the user row takes `message_id`; the waiting placeholder (if
 *   the page added one) becomes the live row of `run_id`. A new run without a
 *   placeholder gets its live row right after the user row.
 * - `queued`: the user row takes `message_id` (the run store marks it as
 *   queued by that id) and the placeholder goes away: no run answers yet.
 */
export function reconcileSentMessages(
    messages: ChatMessage[],
    outcome: Extract<SendOutcome, { kind: 'started' | 'queued' }>,
    refs: SentMessageRefs,
): ChatMessage[] {
    const { result } = outcome;
    const serverId = result.message_id || refs.userMessageId;
    const conversationId = result.conversation_id;
    let next = messages.map((m) => {
        if (m.messageId === refs.userMessageId) {
            return { ...m, messageId: serverId, ...(conversationId ? { conversationId } : {}) };
        }
        if (m.parentMessageId === refs.userMessageId) return { ...m, parentMessageId: serverId };
        return m;
    });
    if (outcome.kind === 'queued') {
        return next.filter((m) => m.liveRunId !== '');
    }
    if (refs.answered) {
        return next.filter((m) => m.messageId !== serverId && m.liveRunId !== '');
    }
    const alreadyLive = next.some((m) => m.liveRunId === result.run_id);
    const pendingIndex = next.findIndex((m) => m.liveRunId === '');
    if (pendingIndex !== -1) {
        if (alreadyLive) return next.filter((_, i) => i !== pendingIndex);
        next = next.slice();
        next[pendingIndex] = {
            ...next[pendingIndex],
            liveRunId: result.run_id,
            messageId: `run:${result.run_id}`,
            ...(conversationId ? { conversationId } : {}),
        };
        return next;
    }
    if (alreadyLive || refs.runKnown) return next;
    const userIndex = next.findIndex((m) => m.messageId === serverId);
    if (userIndex === -1) return next;
    const row = newLiveRow(result.run_id, next[userIndex], refs.sender);
    return [...next.slice(0, userIndex + 1), row, ...next.slice(userIndex + 1)];
}

/**
 * Apply a blocked send to the optimistic rows: the user row takes the stored
 * question id and the turn gets a plain answer row with the auto-reply, the
 * same shape the history returns for it. No run mirrors this row.
 */
export function applyBlockedSend(messages: ChatMessage[], blocked: BlockedSend, refs: SentMessageRefs): ChatMessage[] {
    const questionId = blocked.questionMessageId || refs.userMessageId;
    const next = messages
        .filter((m) => m.liveRunId !== '')
        .map((m) => {
            if (m.messageId === refs.userMessageId) {
                return { ...m, messageId: questionId, conversationId: blocked.conversationId };
            }
            return m.parentMessageId === refs.userMessageId ? { ...m, parentMessageId: questionId } : m;
        });
    const userIndex = next.findIndex((m) => m.messageId === questionId);
    if (userIndex === -1) return next;
    const answer: ChatMessage = {
        text: blocked.autoReply,
        sender: refs.sender,
        isCreatedByUser: false,
        parentMessageId: questionId,
        conversationId: blocked.conversationId,
        messageId: blocked.answerMessageId || `${questionId}_`,
        error: false,
        category: 'agent_answer',
        events: [{ type: 'text', content: blocked.autoReply }],
    };
    return [...next.slice(0, userIndex + 1), answer, ...next.slice(userIndex + 1)];
}

/** Drop the optimistic rows of a send that was rejected. */
export function dropSentMessages(messages: ChatMessage[], userMessageId: string): ChatMessage[] {
    return messages.filter((m) => m.messageId !== userMessageId && m.liveRunId !== '');
}

/**
 * Whether a history response already holds the answer of the turn that just
 * ended. The answer row is written when the run ends, which can be a moment
 * after the terminal event reached the page.
 */
export function historyHasAnswer(history: ChatMessage[]): boolean {
    const last = history[history.length - 1];
    return !!last && !last.isCreatedByUser;
}

/**
 * The list to show after a history reload: the persisted rows, followed by the
 * local user rows that still wait in the inbox (they are stored only when the
 * agent reads them, so the history does not hold them yet).
 */
export function mergeHistoryWithQueued(
    history: ChatMessage[],
    local: ChatMessage[],
    queuedMessageIds: Record<string, unknown> | null | undefined,
): ChatMessage[] {
    const queued = queuedMessageIds ?? {};
    // A message sent into a run is stored at once; its row carries the inbox id.
    const known = new Set(history.flatMap((m) => [String(m.messageId), queueIdOf(m)]));
    const waiting = local.filter((m) => m.isCreatedByUser && !!queued[queueIdOf(m)] && !known.has(queueIdOf(m)));
    return waiting.length ? [...history, ...waiting] : history;
}

/**
 * Ids, among the messages the run store marks as queued, that a history
 * response shows as read: the row of the message is stored and no longer
 * carries the "queued" mark. Used after a `resync`, when the `steer_read`
 * events that clear the marks may have been missed. A message without a
 * stored row is left alone.
 */
export function readQueuedIds(
    history: ChatMessage[],
    queuedMessageIds: Record<string, unknown> | null | undefined,
): string[] {
    const queued = queuedMessageIds ?? {};
    const read: string[] = [];
    for (const row of history) {
        if (row.isCreatedByUser && row.steerMessageId && !row.steerQueued && queued[row.steerMessageId]) {
            read.push(row.steerMessageId);
        }
    }
    return read;
}

// ---------------------------------------------------------------------------
// Unread messages given back (design §7 items 1, 6)
// ---------------------------------------------------------------------------

/** Ids, among `ids`, of returned messages whose user row is in the list. */
export function shownReturnedIds(messages: ChatMessage[], ids: Iterable<string>): Set<string> {
    const wanted = new Set(ids);
    const shown = new Set<string>();
    for (const m of messages) {
        if (m.isCreatedByUser && wanted.has(queueIdOf(m))) shown.add(queueIdOf(m));
    }
    return shown;
}

/** Remove the user rows of returned messages; their text goes back to the input box. */
export function removeReturnedMessages(messages: ChatMessage[], ids: ReadonlySet<string>): ChatMessage[] {
    if (ids.size === 0) return messages;
    const next = messages.filter((m) => !(m.isCreatedByUser && ids.has(queueIdOf(m))));
    return next.length === messages.length ? messages : next;
}
