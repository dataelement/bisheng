import {
    emptyConversationRunState,
    reduceRunEvent,
    reduceSendResult,
    RunEvent,
    selectCanSend,
    selectIsMessageQueued,
    selectIsRunning,
    selectLastEventId,
    selectPlanProgress,
    selectRun,
    useRunStore,
} from './runStore';

const CID = 'conv-1';

let seq = 0;
function nextId(): string {
    seq += 1;
    return `1700000000000-${seq}`;
}

function apply(event: RunEvent, entryId: string = nextId()) {
    useRunStore.getState().applyEvent(CID, event, entryId);
}

const state = () => useRunStore.getState();

beforeEach(() => {
    seq = 0;
    useRunStore.setState({ conversations: {} });
});

describe('store/runStore', () => {
    it('merges text', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        apply({ type: 'text', run_id: 'r1', data: { text: 'Hel' } });
        apply({ type: 'text', run_id: 'r1', data: { text: 'lo' } });
        apply({ type: 'thinking', run_id: 'r1', data: { text: 'a', call_id: 'c1' } });
        apply({ type: 'thinking', run_id: 'r1', data: { text: 'b', call_id: 'c1' } });
        apply({ type: 'thinking', run_id: 'r1', data: { text: 'x', call_id: 'c1', namespace: 'sub' } });
        const run = selectRun(CID)(state())!;
        expect(run.text).toBe('Hello');
        expect(run.thinking.map((s) => [s.callId, s.namespace, s.text])).toEqual([
            ['c1', null, 'ab'],
            ['c1', 'sub', 'x'],
        ]);
    });

    it('merges tool call start and end by call_id', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        apply({
            type: 'tool_call',
            run_id: 'r1',
            data: { call_id: 't1', name: 'web_search', status: 'start', params: { q: 'x' } },
        });
        apply({ type: 'tool_call', run_id: 'r1', data: { call_id: 't1', name: 'web_search', status: 'end', output: 'ok' } });
        const calls = selectRun(CID)(state())!.toolCalls;
        expect(calls).toHaveLength(1);
        expect(calls[0]).toMatchObject({ callId: 't1', status: 'done', params: { q: 'x' }, output: 'ok' });
    });

    it('replaces plan', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        apply({
            type: 'plan',
            run_id: 'r1',
            data: {
                items: [
                    { id: 'a', content: 'A', status: 'completed' },
                    { id: 'b', content: 'B', status: 'in_progress' },
                ],
            },
        });
        apply({
            type: 'plan',
            run_id: 'r1',
            data: {
                items: [
                    { id: 'a', content: 'A', status: 'completed' },
                    { id: 'c', content: 'C2', previous_content: 'C', status: 'pending' },
                    { id: 'b', content: 'B', status: 'cancelled' },
                ],
            },
        });
        const plan = selectRun(CID)(state())!.plan;
        expect(plan.map((i) => i.id)).toEqual(['a', 'c', 'b']);
        expect(plan[1].previous_content).toBe('C');
        // Cancelled rows count in neither number (same rule as backend plan_progress).
        expect(selectPlanProgress(CID)(state())).toEqual({ done: 1, total: 2 });
        // Same plan array -> same progress object (stable selector output).
        expect(selectPlanProgress(CID)(state())).toBe(selectPlanProgress(CID)(state()));
    });

    it('steer queued then cleared', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        apply({ type: 'steer_accepted', run_id: 'r1', data: { message_id: 'm2' } });
        expect(selectIsMessageQueued(CID, 'm2')(state())).toBe(true);
        expect(selectIsMessageQueued(CID, 'm3')(state())).toBe(false);
        apply({ type: 'steer_read', run_id: 'r1', data: { message_id: 'm2' } });
        expect(selectIsMessageQueued(CID, 'm2')(state())).toBe(false);
    });

    it('marks a queued send result and clears it on steer_read', () => {
        state().applySendResult(CID, { run_id: 'r1', disposition: 'queued', message_id: '42' });
        expect(selectIsMessageQueued(CID, 42)(state())).toBe(true);
        apply({ type: 'steer_read', run_id: 'r1', data: { message_id: '42' } });
        expect(selectIsMessageQueued(CID, 42)(state())).toBe(false);
    });

    it('resync replaces run', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        apply({ type: 'text', run_id: 'r1', data: { text: 'partial' } });
        apply({ type: 'tool_call', run_id: 'r1', data: { call_id: 't1', name: 'x', status: 'start' } });
        apply(
            {
                type: 'resync',
                run_id: 'r1',
                data: {
                    text: 'full text',
                    thinking: 'th',
                    plan: [{ id: 'a', content: 'A', status: 'pending' }],
                    files: [
                        { file_id: 'f1', name: 'a.md', path: 'p/a.md' },
                        { file_id: 'f1', name: 'a.md', path: 'p/a.md' },
                    ],
                },
            },
            '1700000000999-0',
        );
        const run = selectRun(CID)(state())!;
        expect(run.text).toBe('full text');
        expect(run.thinking.map((s) => s.text)).toEqual(['th']);
        expect(run.toolCalls).toEqual([]);
        expect(run.plan).toHaveLength(1);
        expect(run.files).toHaveLength(1);
        expect(run.status).toBe('running');
        expect(selectLastEventId(CID)(state())).toBe('1700000000999-0');
    });

    it('resync with a pending question waits for the answer', () => {
        state().applyResync(
            CID,
            'r2',
            { text: '', thinking: '', plan: [], files: [], pending_question: { call_id: 'q', questions: [] } },
            '1-1',
        );
        expect(selectRun(CID)(state())!.status).toBe('waiting');
        expect(selectIsRunning(CID)(state())).toBe(true);
    });

    it('resync of an ended run takes the status the backend reports', () => {
        const base = { text: 'done', thinking: '', plan: [], files: [] };
        state().applyResync(CID, 'r3', { ...base, ended: true, status: 'stopped' }, '2-1');
        expect(selectRun(CID)(state())!.status).toBe('stopped');
        expect(selectIsRunning(CID)(state())).toBe(false);
        state().applyResync(CID, 'r4', { ...base, ended: true, pending_question: { call_id: 'q', questions: [] } }, '3-1');
        expect(selectRun(CID)(state())!.status).toBe('finished');
        expect(selectRun(CID)(state())!.pendingQuestion).toBeNull();
        state().applyResync(CID, 'r5', { ...base, ended: false }, '4-1');
        expect(selectRun(CID)(state())!.status).toBe('running');
    });

    it('running flags', () => {
        expect(selectIsRunning(CID)(state())).toBe(false);
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        expect(selectIsRunning(CID)(state())).toBe(true);
        apply({ type: 'text', run_id: 'r1', data: { text: 'x' } });
        expect(selectIsRunning(CID)(state())).toBe(true);
        apply({ type: 'run_finished', run_id: 'r1', data: {} });
        expect(selectIsRunning(CID)(state())).toBe(false);
        expect(selectRun(CID)(state())!.status).toBe('finished');

        apply({ type: 'run_started', run_id: 'r2', data: {} });
        apply({
            type: 'run_failed',
            run_id: 'r2',
            data: { code: 11091, reason: 'x', detail: 'y', reference_id: 'ref' },
        });
        expect(selectRun(CID)(state())).toMatchObject({ status: 'failed', error: { code: 11091 } });

        apply({ type: 'run_started', run_id: 'r3', data: {} });
        apply({ type: 'run_stopped', run_id: 'r3', data: {} });
        expect(selectRun(CID)(state())!.status).toBe('stopped');
        expect(selectIsRunning(CID)(state())).toBe(false);
    });

    it('pending question', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        apply({
            type: 'ask_user',
            run_id: 'r1',
            data: { call_id: 'q1', questions: [{ question: 'Which?', options: ['A', 'B'] }] },
        });
        let run = selectRun(CID)(state())!;
        expect(run.status).toBe('waiting');
        expect(run.pendingQuestion?.call_id).toBe('q1');
        expect(selectIsRunning(CID)(state())).toBe(true);
        apply({ type: 'ask_user_answered', run_id: 'r1', data: { call_id: 'q1', answer: 'A' } });
        run = selectRun(CID)(state())!;
        expect(run.status).toBe('running');
        expect(run.pendingQuestion).toBeNull();
    });

    it('file dedupe', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        apply({ type: 'file', run_id: 'r1', data: { file_id: 'f1', name: 'a.md', path: 'p/a.md' } });
        apply({ type: 'file', run_id: 'r1', data: { file_id: 'f2', name: 'b.md', path: 'p/b.md' } });
        apply({ type: 'file', run_id: 'r1', data: { file_id: 'f1', name: 'a.md', path: 'p/a.md', size: 3 } });
        const files = selectRun(CID)(state())!.files;
        expect(files.map((f) => f.file_id)).toEqual(['f1', 'f2']);
        expect(files[0].size).toBe(3);
    });

    it('can send while running', () => {
        expect(selectCanSend(CID)(state())).toBe(true);
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        expect(selectIsRunning(CID)(state())).toBe(true);
        expect(selectCanSend(CID)(state())).toBe(true);
        apply({ type: 'ask_user', run_id: 'r1', data: { call_id: 'q', questions: [] } });
        expect(selectCanSend(CID)(state())).toBe(true);
    });

    it('ignores stale events of an older run', () => {
        // Send response names the new run before its run_started arrives.
        apply({ type: 'run_started', run_id: 'old', data: {} });
        apply({ type: 'text', run_id: 'old', data: { text: 'old answer' } });
        state().applySendResult(CID, { run_id: 'new', disposition: 'started', message_id: 'm9' });
        apply({ type: 'text', run_id: 'old', data: { text: ' leftover' } });
        apply({ type: 'run_finished', run_id: 'old', data: {} });
        let run = selectRun(CID)(state())!;
        expect(run.runId).toBe('new');
        expect(run.text).toBe('');
        expect(run.status).toBe('running');
        apply({ type: 'run_started', run_id: 'new', data: {} });
        apply({ type: 'text', run_id: 'new', data: { text: 'fresh' } });
        run = selectRun(CID)(state())!;
        expect(run.text).toBe('fresh');
    });

    it('ignores unknown run events while the current run is live', () => {
        state().applySendResult(CID, { run_id: 'new', disposition: 'started', message_id: 'm1' });
        apply({ type: 'text', run_id: 'never-seen', data: { text: 'stale' } });
        expect(selectRun(CID)(state())!.text).toBe('');
    });

    it('skips a replayed entry after reconnect', () => {
        apply({ type: 'run_started', run_id: 'r1', data: {} }, '10-0');
        apply({ type: 'text', run_id: 'r1', data: { text: 'a' } }, '10-1');
        apply({ type: 'text', run_id: 'r1', data: { text: 'a' } }, '10-1');
        apply({ type: 'text', run_id: 'r1', data: { text: 'b' } }, '10-2');
        expect(selectRun(CID)(state())!.text).toBe('ab');
        expect(selectLastEventId(CID)(state())).toBe('10-2');
    });

    it('adopts a run when subscribing mid-run without run_started', () => {
        apply({ type: 'text', run_id: 'r1', data: { text: 'mid' } });
        expect(selectRun(CID)(state())).toMatchObject({ runId: 'r1', status: 'running', text: 'mid' });
    });

    it('keeps conversations apart and reducers pure', () => {
        const before = emptyConversationRunState();
        const after = reduceRunEvent(before, { type: 'run_started', run_id: 'r1', data: {} }, '1-0');
        expect(before.run).toBeNull();
        expect(after.run?.runId).toBe('r1');
        const queued = reduceSendResult(after, { run_id: 'r1', disposition: 'queued', message_id: 'm' });
        expect(after.queuedMessages).toEqual({});
        expect(queued.queuedMessages).toEqual({ m: true });
        apply({ type: 'run_started', run_id: 'r1', data: {} });
        expect(selectRun('other')(state())).toBeNull();
    });
});
