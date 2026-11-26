/**
 * F004 design §7 items 2, 3 and 6 — pure helpers: the stopped mark of an
 * answer, a blocked send, and the rows of unread messages given back.
 */
import type { ChatMessage } from '~/api/chatApi';
import { emptyConversationRunState, reduceRunEvent, type RunState } from '~/store/runStore';
import {
    STOPPED_TOOL_NOTE,
    addEndedRunRow,
    applyBlockedSend,
    classifySendResponse,
    freezeLiveRun,
    mergeHistoryWithQueued,
    queueIdOf,
    removeReturnedMessages,
    runRowMarks,
    shownReturnedIds,
} from './unifiedRun';

const row = (id: string, isCreatedByUser: boolean, extra: Partial<ChatMessage> = {}): ChatMessage => ({
    text: id,
    sender: isCreatedByUser ? 'User' : 'AI',
    isCreatedByUser,
    messageId: id,
    parentMessageId: '',
    conversationId: 'c1',
    error: false,
    ...extra,
});

function runAfter(events: Array<Record<string, unknown>>): RunState {
    let conv = emptyConversationRunState();
    for (const event of events) conv = reduceRunEvent(conv, { run_id: 'r1', data: {}, ...event } as never);
    return conv.run as RunState;
}

describe('stopped answer (item 2)', () => {
    it('freezes the live row of a stopped run with its content and the stopped mark, not as an error', () => {
        const run = runAfter([
            { type: 'run_started' },
            { type: 'text', data: { text: 'so far' } },
            { type: 'tool_call', data: { call_id: 't1', name: 'search', status: 'start' } },
            { type: 'tool_call', data: { call_id: 't1', name: 'search', status: 'end', output: 'ok' } },
            { type: 'tool_call', data: { call_id: 't2', name: 'code', status: 'start' } },
            { type: 'run_stopped', data: { reason: 'user', status: 'stopped', unread_messages: [] } },
        ]);
        const [, frozen] = freezeLiveRun([row('q', true), row('run:r1', false, { liveRunId: 'r1', text: '' })], run, 'unused');
        expect(frozen.liveRunId).toBeUndefined();
        expect(frozen).toMatchObject({ text: 'so far', stopped: true, error: false });
        expect(frozen.errorText).toBeUndefined();
        const tools = (frozen.events ?? []).filter((e) => e.type === 'tool_call');
        expect(tools[0]).toMatchObject({ tool_call_id: 't1', inflight: false, results: 'ok' });
        expect((tools[0] as { error?: string }).error).toBeUndefined();
        expect(tools[1]).toMatchObject({ tool_call_id: 't2', inflight: false, error: STOPPED_TOOL_NOTE });
    });

    it('does not mark a failed or finished run as stopped', () => {
        const failed = runAfter([{ type: 'run_started' }, { type: 'run_failed', data: { code: 1, reason: 'x', detail: 'd' } }]);
        const [frozen] = freezeLiveRun([row('run:r1', false, { liveRunId: 'r1' })], failed, 'failed');
        expect(frozen.stopped).toBeUndefined();
        expect(frozen.error).toBe(true);
    });

    it('gives the frozen row the files of the stored answer, with the row ids', () => {
        const copied = { file_id: 'copy-1', workspace_file_id: 'live-1', file_name: 'a.md', path: 'output/a.md', source: 'code_interpreter', object_name: 'chat/7/answers/r1/live-1.md' };
        // A copy that failed on the backend: the row keeps the event id.
        const kept = { file_id: 'live-2', file_name: 'b.md', path: 'output/b.md', source: 'code_interpreter', object_name: 'workspace/c1/output/b.md' };
        for (const type of ['run_finished', 'run_stopped', 'run_failed']) {
            const run = runAfter([
                { type: 'run_started' },
                { type: 'file', data: { file_id: 'live-1', name: 'a.md', path: 'output/a.md' } },
                { type: 'file', data: { file_id: 'live-2', name: 'b.md', path: 'output/b.md' } },
                { type, data: { code: 1, reason: 'x', detail: 'd', answer_files: [copied, kept] } },
            ]);
            const [frozen] = freezeLiveRun([row('run:r1', false, { liveRunId: 'r1' })], run, 'failed');
            expect(frozen.files).toEqual([copied, kept]);
        }
        // No `answer_files` on the event: the row waits for the history.
        const bare = runAfter([{ type: 'run_started' }, { type: 'file', data: { file_id: 'live-1', name: 'a.md', path: 'output/a.md' } }, { type: 'run_finished' }]);
        expect(freezeLiveRun([row('run:r1', false, { liveRunId: 'r1' })], bare)[0].files).toBeUndefined();
    });

    it('reads the stopped mark and the inbox id out of a history row', () => {
        expect(runRowMarks({ status: 'stopped', run_id: 'r1' })).toEqual({ stopped: true });
        // A run torn down without a terminal event stays an error row.
        expect(runRowMarks({ error: true, error_msg: 'stream interrupted' })).toEqual({});
        expect(runRowMarks({ status: 'stopped', error: true })).toEqual({});
        expect(runRowMarks({ run_id: 'r1', steer_message_id: 'm1', queued: true })).toEqual({
            steerMessageId: 'm1',
            steerQueued: true,
        });
        expect(runRowMarks(undefined)).toEqual({});
        expect(runRowMarks('{"status":"stopped"}')).toEqual({});
    });
});

describe('blocked send (item 3)', () => {
    const body = {
        run_id: null,
        disposition: 'blocked',
        message_id: null,
        conversation_id: 'c9',
        content_safety: true,
        auto_reply: 'not allowed',
        question_message_id: 901,
        answer_message_id: 902,
    };

    it('classifies the JSON answer, bare or in the response envelope', () => {
        const expected = {
            kind: 'blocked',
            blocked: { conversationId: 'c9', autoReply: 'not allowed', questionMessageId: '901', answerMessageId: '902' },
        };
        expect(classifySendResponse(body)).toEqual(expected);
        expect(classifySendResponse({ status_code: 200, data: body })).toEqual(expected);
        expect(classifySendResponse({ ...body, conversation_id: '' })).toEqual({ kind: 'invalid' });
    });

    it('turns the optimistic rows into the stored question and an answer with the auto-reply', () => {
        const optimistic = [row('old', false), row('u1', true, { text: 'bad words' }), row('u1_', false, { liveRunId: '', parentMessageId: 'u1', text: '' })];
        const outcome = classifySendResponse(body);
        if (outcome.kind !== 'blocked') throw new Error('expected blocked');
        const next = applyBlockedSend(optimistic, outcome.blocked, { userMessageId: 'u1', sender: 'Model' });
        expect(next.map((m) => m.messageId)).toEqual(['old', '901', '902']);
        expect(next[1]).toMatchObject({ text: 'bad words', conversationId: 'c9' });
        expect(next[2]).toMatchObject({
            text: 'not allowed',
            sender: 'Model',
            parentMessageId: '901',
            conversationId: 'c9',
            category: 'agent_answer',
            error: false,
            events: [{ type: 'text', content: 'not allowed' }],
        });
        expect(next.some((m) => m.liveRunId !== undefined)).toBe(false);
    });

    it('puts the answer right after the question when no placeholder was added', () => {
        const next = applyBlockedSend(
            [row('u1', true), row('later', true)],
            { conversationId: 'c9', autoReply: 'no', questionMessageId: '', answerMessageId: '' },
            { userMessageId: 'u1', sender: 'AI' },
        );
        expect(next.map((m) => m.messageId)).toEqual(['u1', 'u1_', 'later']);
    });
});

describe('rows of unread messages given back (items 1, 6)', () => {
    const local = [row('q', true), row('a', false), row('m1', true), row('8801', true, { steerMessageId: 'm2' })];

    it('knows a user row by its inbox id when it was sent into a run', () => {
        expect(queueIdOf(local[2])).toBe('m1');
        expect(queueIdOf(local[3])).toBe('m2');
    });

    it('finds and removes the rows of the returned messages only', () => {
        const shown = shownReturnedIds(local, ['m1', 'm2', 'gone']);
        expect([...shown]).toEqual(['m1', 'm2']);
        expect(removeReturnedMessages(local, shown).map((m) => m.messageId)).toEqual(['q', 'a']);
        expect(removeReturnedMessages(local, new Set(['gone']))).toBe(local);
        // An answer row is never removed, whatever its id.
        expect(removeReturnedMessages(local, new Set(['a']))).toBe(local);
    });

    it('does not show a queued message twice when the history already holds its row', () => {
        const history = [row('q', true), row('8801', true, { steerMessageId: 'm2' })];
        const merged = mergeHistoryWithQueued(history, [row('q', true), row('m2', true), row('m3', true)], { m2: true, m3: true });
        expect(merged.map((m) => m.messageId)).toEqual(['q', '8801', 'm3']);
    });

    it('gives a failed run that never had a row its failure row, once', () => {
        const failed = runAfter([
            { type: 'run_started', data: { relay: true } },
            { type: 'run_failed', data: { code: 11091, reason: 'task_aborted', detail: 'boom', reference_id: 'r1' } },
        ]);
        const next = addEndedRunRow([row('q', true), row('a', false)], failed, 'AI', 'failed');
        expect(next[2]).toMatchObject({ messageId: 'run:r1', error: true, errorText: '', errorCode: 11091, referenceId: 'r1' });
        expect(next[2].liveRunId).toBeUndefined();
        expect(addEndedRunRow(next, failed, 'AI', 'failed')).toBe(next);
    });
});
