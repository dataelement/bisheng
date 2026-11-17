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
import type { AgentEvent, ChatMessage } from '~/api/chatApi';
import type { RunSendResult, RunState } from '~/store/runStore';

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
    | { kind: 'invalid' };

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

// ---------------------------------------------------------------------------
// Live row
// ---------------------------------------------------------------------------

export function isRunActive(run: RunState | null | undefined): boolean {
    return run?.status === 'running' || run?.status === 'waiting';
}

/** Thinking segments and tool calls of a run as the ordered event log the bubbles render. */
export function agentEventsOfRun(run: RunState): AgentEvent[] {
    const items: Array<{ order: number; event: AgentEvent }> = [];
    for (const segment of run.thinking) {
        items.push({ order: segment.order ?? 0, event: { type: 'thinking', content: segment.text } });
    }
    for (const call of run.toolCalls) {
        const displayName = call.extraInfo?.display_name;
        const args =
            call.params && typeof call.params === 'object' && !Array.isArray(call.params)
                ? (call.params as Record<string, unknown>)
                : call.params == null
                  ? undefined
                  : { input: call.params };
        items.push({
            order: call.order ?? 0,
            event: {
                type: 'tool_call',
                tool_call_id: call.callId,
                tool_name: call.name,
                ...(typeof displayName === 'string' && displayName ? { display_name: displayName } : {}),
                tool_type: call.stepType,
                ...(args ? { args } : {}),
                ...(call.output != null ? { results: call.output } : {}),
                inflight: call.status === 'running',
            },
        });
    }
    // Stable: equal ranks keep "thinking before tool call".
    return items
        .map((item, index) => ({ ...item, index }))
        .sort((a, b) => a.order - b.order || a.index - b.index)
        .map((item) => item.event);
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

/** Failure fields of the answer row of a failed run. `errorText` is the localized copy. */
export function failureFieldsOfRun(run: RunState, errorText: string): Partial<ChatMessage> {
    if (run.status !== 'failed') return {};
    const error = run.error;
    return {
        error: true,
        errorText,
        ...(error?.code != null ? { errorCode: error.code } : {}),
        ...(error?.reason ? { errorType: error.reason } : {}),
        ...(error?.detail ? { errorDetail: error.detail } : {}),
        ...(error?.reference_id ? { referenceId: error.reference_id } : {}),
    };
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
    next[index] = { ...messages[index], ...liveFieldsOfRun(run) };
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

/** Whether the list holds the live row of this run. */
export function hasLiveRow(messages: ChatMessage[], runId: string): boolean {
    return messages.some((m) => m.liveRunId === runId);
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
    next[index] = { ...row, ...liveFieldsOfRun(run), ...failureFieldsOfRun(run, errorText) };
    return next;
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
    const known = new Set(history.map((m) => String(m.messageId)));
    const waiting = local.filter(
        (m) => m.isCreatedByUser && !!queued[String(m.messageId)] && !known.has(String(m.messageId)),
    );
    return waiting.length ? [...history, ...waiting] : history;
}
