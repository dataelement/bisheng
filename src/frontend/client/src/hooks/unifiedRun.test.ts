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
    reconcileSentMessages,
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
