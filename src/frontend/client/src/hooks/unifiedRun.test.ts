import type { ChatMessage } from '~/api/chatApi';
import { emptyConversationRunState, reduceRunEvent, type RunEvent, type RunState } from '~/store/runStore';
import {
    addLiveRow,
    agentEventsOfRun,
    classifySendResponse,
    dropSentMessages,
    freezeLiveRun,
    historyHasAnswer,
    isAnswerToPendingQuestion,
    mergeHistoryWithQueued,
    needsLiveRow,
    parseLegacySendFrames,
    readQueuedIds,
    reconcileSentMessages,
    runRowMarks,
    settleReplacedRun,
    withLiveRun,
} from './unifiedRun';

function runOf(events: Array<Record<string, unknown>>): RunState {
    let conv = emptyConversationRunState();
    events.forEach((event, i) => {
        conv = reduceRunEvent(conv, { run_id: 'r1', data: {}, ...event } as RunEvent, `1-${i}`);
    });
    return conv.run as RunState;
}

const user = (id: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
    messageId: id, parentMessageId: '', conversationId: 'c1', sender: 'User', text: id, isCreatedByUser: true, ...extra,
});
const bot = (id: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
    messageId: id, parentMessageId: '', conversationId: 'c1', sender: 'AI', text: id, isCreatedByUser: false, ...extra,
});
const started = (extra: Record<string, unknown> = {}) =>
    classifySendResponse({ status_code: 200, data: { run_id: 'r1', disposition: 'started', message_id: 'm1', ...extra } }) as
        Extract<ReturnType<typeof classifySendResponse>, { kind: 'started' }>;
const queued = () =>
    classifySendResponse({ status_code: 200, data: { run_id: 'r1', disposition: 'queued', message_id: 'm2' } }) as
        Extract<ReturnType<typeof classifySendResponse>, { kind: 'queued' }>;

describe('classifySendResponse', () => {
    it('reads started and queued from the JSON envelope', () => {
        const a = started({ conversation_id: 'c9' });
        expect(a.kind).toBe('started');
        expect(a.result).toEqual({ run_id: 'r1', disposition: 'started', message_id: 'm1', conversation_id: 'c9' });
        expect(queued().kind).toBe('queued');
    });

    it('accepts the bare data object too', () => {
        expect(classifySendResponse({ run_id: 'r', disposition: 'queued', message_id: 5 })).toEqual({
            kind: 'queued',
            result: { run_id: 'r', disposition: 'queued', message_id: '5' },
        });
    });

    it('rejects an unknown disposition or a body without a run', () => {
        expect(classifySendResponse({ data: { run_id: 'r', disposition: 'later', message_id: 'm' } }).kind).toBe('invalid');
        expect(classifySendResponse({ status_code: 200, data: null }).kind).toBe('invalid');
        expect(classifySendResponse(null).kind).toBe('invalid');
    });

    it('recognises the legacy SSE text of a blocked input', () => {
        const body = [
            'data: {"created": true, "message": {"conversationId": "c7", "messageId": 12}}',
            'data: {"final": true, "conversation": {"conversationId": "c7"}}',
            '',
        ].join('\n\n');
        expect(classifySendResponse(body)).toEqual({ kind: 'legacy', conversationId: 'c7', error: null });
    });

    it('reads an error frame from legacy SSE text', () => {
        const body = 'event: error\ndata: {"status_code": 12046, "status_message": "busy"}\n\n';
        expect(parseLegacySendFrames(body)).toEqual({ conversationId: null, error: { code: 12046, message: 'busy' } });
    });
});

describe('isAnswerToPendingQuestion', () => {
    it('is true only for the run that waits', () => {
        const waiting = runOf([{ type: 'run_started' }, { type: 'ask_user', data: { call_id: 'c', questions: [] } }]);
        expect(isAnswerToPendingQuestion(waiting, started().result)).toBe(true);
        expect(isAnswerToPendingQuestion(waiting, started({ run_id: 'r2' }).result)).toBe(false);
        expect(isAnswerToPendingQuestion(runOf([{ type: 'run_started' }]), started().result)).toBe(false);
    });
});

describe('live row', () => {
    const run = runOf([
        { type: 'run_started' },
        { type: 'thinking', data: { text: 'plan it', call_id: 't1' } },
        { type: 'tool_call', data: { call_id: 'k1', name: 'search', status: 'start', params: { q: 'x' } } },
        { type: 'thinking', data: { text: 'read it', call_id: 't2' } },
        { type: 'tool_call', data: { call_id: 'k1', name: 'search', status: 'end', output: 'found' } },
        { type: 'text', data: { text: 'Answer' } },
    ]);

    it('orders thinking and tool calls by arrival', () => {
        expect(agentEventsOfRun(run)).toEqual([
            { type: 'thinking', content: 'plan it' },
            {
                type: 'tool_call', tool_call_id: 'k1', tool_name: 'search', tool_type: 'tool',
                args: { q: 'x' }, results: 'found', inflight: false,
            },
            { type: 'thinking', content: 'read it' },
        ]);
    });

    it('shows the run in its row and leaves other rows alone', () => {
        const list = [user('q'), bot('run:r1', { text: '', liveRunId: 'r1' }), user('steer')];
        const shown = withLiveRun(list, run);
        expect(shown[1].text).toBe('Answer');
        expect(shown[1].category).toBe('agent_answer');
        expect(shown[1].events).toHaveLength(3);
        expect(shown[0]).toBe(list[0]);
        expect(shown[2]).toBe(list[2]);
        expect(withLiveRun([user('q'), bot('a')], run)).toHaveLength(2);
    });

    it('adds a row for a run the page did not start only after a user message', () => {
        expect(needsLiveRow([user('q')], run)).toBe(true);
        expect(needsLiveRow([user('q'), bot('task row')], run)).toBe(false);
        expect(needsLiveRow([], run)).toBe(false);
        expect(needsLiveRow([user('q'), bot('p', { liveRunId: '' })], run)).toBe(false);
        expect(needsLiveRow([user('q'), bot('p', { liveRunId: 'r1' })], run)).toBe(false);
        const ended = runOf([{ type: 'run_started' }, { type: 'run_finished' }]);
        expect(needsLiveRow([user('q')], ended)).toBe(false);
        const added = addLiveRow([user('q')], run, 'Model');
        expect(added[1]).toMatchObject({ liveRunId: 'r1', messageId: 'run:r1', parentMessageId: 'q', sender: 'Model' });
    });

    it('freezes the final state so the stored turn can replace it without a second copy', () => {
        const failed = runOf([
            { type: 'run_started' },
            { type: 'text', data: { text: 'partial' } },
            { type: 'run_failed', data: { code: 12045, reason: 'internal', detail: 'boom', reference_id: 'ref' } },
        ]);
        const frozen = freezeLiveRun([user('q'), bot('run:r1', { liveRunId: 'r1' })], failed, 'It failed');
        expect(frozen[1].liveRunId).toBeUndefined();
        expect(frozen[1]).toMatchObject({
            text: 'partial', error: true, errorText: 'It failed', errorCode: 12045, errorType: 'internal',
            errorDetail: 'boom', referenceId: 'ref',
        });
        // No row carries the mark any more, so nothing mirrors the store.
        expect(withLiveRun(frozen, failed)).toBe(frozen);
    });

    // 114, 2026-11-18: the live failure and the reloaded one must carry the same
    // fields. The copy of an umbrella code is deep-research wording, so it is
    // not kept as the row's text; the dependency provenance is kept.
    it('gives a failed direct run the fields the stored row has', () => {
        const failureInfo = {
            version: 1, failure_id: 'f-1', category: 'model_service', service: 'llm', occurred_at: '2026-11-18T08:00:00Z',
        };
        const failed = runOf([
            { type: 'run_started' },
            {
                type: 'run_failed',
                data: { code: 11091, reason: 'chat_unknown', detail: 'ValueError: boom', reference_id: 'r1', failure_info: failureInfo },
            },
        ]);
        const frozen = freezeLiveRun([user('q'), bot('run:r1', { liveRunId: 'r1' })], failed, 'copy of code 11091');
        expect(frozen[1]).toMatchObject({
            error: true, errorText: '', errorCode: 11091, errorType: 'chat_unknown',
            errorDetail: 'ValueError: boom', referenceId: 'r1', failureInfo,
        });
    });
});

describe('answered question in the live row', () => {
    it('the ask_user call is no longer in flight and carries the question and the answer', () => {
        const question = { call_id: 'k1', questions: [{ question: 'which?' }] };
        const run = runOf([
            { type: 'run_started' },
            { type: 'tool_call', data: { call_id: 'k1', name: 'ask_user', status: 'start' } },
            { type: 'ask_user', data: question },
            { type: 'ask_user_answered', data: { call_id: 'k1', answer: 'A' } },
        ]);
        expect(agentEventsOfRun(run)).toEqual([
            expect.objectContaining({ type: 'tool_call', tool_name: 'ask_user', args: question, results: 'A', inflight: false }),
        ]);
    });
});

describe('reconcileSentMessages', () => {
    const refs = { userMessageId: 'tmp', sender: 'Model' };

    it('started: the question takes the server id and the waiting row becomes the live row', () => {
        const list = [user('tmp'), bot('tmp_', { parentMessageId: 'tmp', liveRunId: '' })];
        const next = reconcileSentMessages(list, started({ conversation_id: 'c9' }), refs);
        expect(next[0]).toMatchObject({ messageId: 'm1', conversationId: 'c9' });
        expect(next[1]).toMatchObject({ messageId: 'run:r1', liveRunId: 'r1', parentMessageId: 'm1' });
    });

    it('queued: the message keeps its place, takes the id the store marks, and no answer row waits', () => {
        const list = [user('q'), bot('run:r1', { liveRunId: 'r1' }), user('tmp')];
        const next = reconcileSentMessages(list, queued(), refs);
        expect(next.map((m) => m.messageId)).toEqual(['q', 'run:r1', 'm2']);
        const idle = reconcileSentMessages([user('tmp'), bot('tmp_', { liveRunId: '' })], queued(), refs);
        expect(idle.map((m) => m.messageId)).toEqual(['m2']);
    });

    it('started as an answer to the pending question adds no second answer row', () => {
        const list = [user('q'), bot('run:r1', { liveRunId: 'r1' }), user('tmp')];
        const next = reconcileSentMessages(list, started(), { ...refs, runKnown: true });
        expect(next.map((m) => m.messageId)).toEqual(['q', 'run:r1', 'm1']);
        const stored = reconcileSentMessages([user('q'), bot('task'), user('tmp')], started(), { ...refs, runKnown: true });
        expect(stored.map((m) => m.messageId)).toEqual(['q', 'task', 'm1']);
    });

    it('an answer to the pending question leaves the list: the answer row shows it', () => {
        const list = [user('q'), bot('run:r1', { liveRunId: 'r1' }), user('tmp')];
        const next = reconcileSentMessages(list, started(), { ...refs, runKnown: true, answered: true });
        expect(next.map((m) => m.messageId)).toEqual(['q', 'run:r1']);
    });

    it('started for a new run without a waiting row puts the live row after the question', () => {
        const next = reconcileSentMessages([bot('old'), user('tmp')], started(), refs);
        expect(next.map((m) => m.messageId)).toEqual(['old', 'm1', 'run:r1']);
    });

    it('a rejected send leaves no optimistic row behind', () => {
        const list = [bot('old'), user('tmp'), bot('tmp_', { liveRunId: '' })];
        expect(dropSentMessages(list, 'tmp').map((m) => m.messageId)).toEqual(['old']);
    });
});

describe('history after a run', () => {
    it('waits for the answer row', () => {
        expect(historyHasAnswer([user('q')])).toBe(false);
        expect(historyHasAnswer([user('q'), bot('a')])).toBe(true);
        expect(historyHasAnswer([])).toBe(false);
    });

    it('keeps messages that still wait in the inbox and nothing else local', () => {
        const history = [user('1'), bot('2')];
        const local = [user('m1'), bot('run:r1'), user('m2'), user('m3')];
        const merged = mergeHistoryWithQueued(history, local, { m2: true });
        expect(merged.map((m) => m.messageId)).toEqual(['1', '2', 'm2']);
        expect(mergeHistoryWithQueued(history, local, {})).toBe(history);
    });
});

describe('event log of a long answer', () => {
    const events: Array<Record<string, unknown>> = [
        { type: 'run_started' },
        { type: 'thinking', data: { text: 'plan it', call_id: 't1' } },
        { type: 'tool_call', data: { call_id: 'k1', name: 'search', status: 'start' } },
        { type: 'thinking', data: { text: 'read', call_id: 't2' } },
    ];
    const next = (run: RunState, event: Record<string, unknown>, i: number): RunState =>
        reduceRunEvent({ ...emptyConversationRunState(), run }, { run_id: 'r1', data: {}, ...event } as RunEvent, `2-${i}`)
            .run as RunState;

    it('a text delta returns the same list: nothing is rebuilt', () => {
        const run = runOf(events);
        const before = agentEventsOfRun(run);
        const after = next(run, { type: 'text', data: { text: 'more' } }, 1);
        expect(after).not.toBe(run);
        expect(agentEventsOfRun(after)).toBe(before);
        const rows = [user('q'), bot('run:r1', { liveRunId: 'r1', text: '' })];
        expect(withLiveRun(rows, run)[1].events).toBe(withLiveRun(rows, after)[1].events);
    });

    it('a thinking delta or a tool call frame renews only the item it changes', () => {
        const run = runOf(events);
        const before = agentEventsOfRun(run);
        const thought = next(run, { type: 'thinking', data: { text: ' it', call_id: 't2' } }, 1);
        const afterThinking = agentEventsOfRun(thought);
        expect(afterThinking[0]).toBe(before[0]);
        expect(afterThinking[1]).toBe(before[1]);
        expect(afterThinking[2]).toEqual({ type: 'thinking', content: 'read it' });
        const called = next(thought, { type: 'tool_call', data: { call_id: 'k1', name: 'search', status: 'end', output: 'found' } }, 2);
        const afterCall = agentEventsOfRun(called);
        expect(afterCall[0]).toBe(before[0]);
        expect(afterCall[2]).toBe(afterThinking[2]);
        expect(afterCall[1]).toMatchObject({ tool_call_id: 'k1', results: 'found', inflight: false });
    });

    it('puts a thinking segment before a tool call of the same rank', () => {
        const run = runOf(events);
        const tied: RunState = {
            ...run,
            thinking: [{ key: 'resync:0', callId: null, namespace: null, text: 'all', order: 0 }],
            toolCalls: run.toolCalls.map((call) => ({ ...call, order: 0 })),
        };
        expect(agentEventsOfRun(tied).map((e) => e.type)).toEqual(['thinking', 'tool_call']);
    });
});

describe('a run another run took the place of', () => {
    it('freezes with its content, as finished, and no tool call left running', () => {
        const run = runOf([
            { type: 'run_started' },
            { type: 'text', data: { text: 'Answer' } },
            { type: 'tool_call', data: { call_id: 'k1', name: 'search', status: 'start' } },
        ]);
        const settled = settleReplacedRun(run);
        expect(settled.status).toBe('finished');
        const rows = freezeLiveRun([user('q'), bot('run:r1', { liveRunId: 'r1', text: '' }), user('m2')], settled);
        expect(rows[1].liveRunId).toBeUndefined();
        expect(rows[1].text).toBe('Answer');
        expect(rows[1].events).toMatchObject([{ tool_call_id: 'k1', inflight: false }]);
        // A run that already ended is taken as it ended.
        const stopped = runOf([{ type: 'run_started' }, { type: 'run_stopped' }]);
        expect(settleReplacedRun(stopped)).toBe(stopped);
    });
});

describe('queued marks against the stored rows', () => {
    it('reads the "queued" mark of a history row', () => {
        expect(runRowMarks({ run_id: 'r1', steer_message_id: 'm1', queued: true })).toEqual({ steerMessageId: 'm1', steerQueued: true });
        expect(runRowMarks({ run_id: 'r1', steer_message_id: 'm1' })).toEqual({ steerMessageId: 'm1', steerQueued: false });
        expect(runRowMarks({ run_id: 'r1', ask_user: { call_id: 'c1', questions: [] } })).toEqual({ answersQuestion: true });
        expect(runRowMarks({})).toEqual({});
    });

    it('names the marked messages whose stored row is no longer queued', () => {
        const history = [
            user('1'),
            user('801', { steerMessageId: 'm1', steerQueued: false }),
            user('802', { steerMessageId: 'm2', steerQueued: true }),
            user('803', { steerMessageId: 'm4', steerQueued: false }),
        ];
        // m3 has no stored row; m4 is not marked.
        expect(readQueuedIds(history, { m1: true, m2: true, m3: true })).toEqual(['m1']);
        expect(readQueuedIds(history, null)).toEqual([]);
    });
});
