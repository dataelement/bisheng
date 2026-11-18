/**
 * F004 (T061): the stored deep-research row of a run in progress.
 */
import type { ChatMessage } from '~/api/chatApi';
import type { RunState } from '~/store/runStore';
import {
    bindLiveTaskRow,
    freezeLiveRun,
    isVersionInProgress,
    liveTaskRowCandidate,
    withLiveRun,
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
const taskRow = (id: string, versionId: string) =>
    row(id, false, { category: 'task', linsightSessionVersionId: versionId, text: '' });
const run = (patch: Partial<RunState> = {}): RunState => ({
    runId: 'r1',
    status: 'running',
    text: '',
    thinking: [],
    toolCalls: [],
    plan: [],
    files: [],
    pendingQuestion: null,
    queuePosition: null,
    error: null,
    answerFiles: null,
    ...patch,
});

describe('liveTaskRowCandidate', () => {
    it('names the last answer row when it is a task row, also behind messages sent into the run', () => {
        expect(liveTaskRowCandidate([row('q', true), taskRow('t', 'sv1')], run())).toEqual({ index: 1, versionId: 'sv1' });
        expect(liveTaskRowCandidate([row('q', true), taskRow('t', 'sv1'), row('steer', true)], run())).toEqual({
            index: 1,
            versionId: 'sv1',
        });
    });

    it('names nothing for an ordinary answer, an ended run, or a run that already has its row', () => {
        expect(liveTaskRowCandidate([row('q', true), row('a', false)], run())).toBeNull();
        expect(liveTaskRowCandidate([row('q', true)], run())).toBeNull();
        expect(liveTaskRowCandidate([taskRow('t', 'sv1')], run({ status: 'finished' }))).toBeNull();
        expect(liveTaskRowCandidate([taskRow('t', 'sv1'), row('live', false, { liveRunId: 'r1' })], run())).toBeNull();
        expect(liveTaskRowCandidate([taskRow('t', 'sv1'), row('wait', false, { liveRunId: '' })], run())).toBeNull();
    });
});

describe('bindLiveTaskRow', () => {
    it('marks the stored row of the run record and shows the run in it, still as a task row', () => {
        const bound = bindLiveTaskRow([row('q', true), taskRow('t', 'sv1')], 'sv1', 'r1');
        expect(bound[1].liveRunId).toBe('r1');
        expect(bound[1].messageId).toBe('t');
        const shown = withLiveRun(bound, run({ text: 'partial answer' }));
        expect(shown[1]).toMatchObject({ text: 'partial answer', category: 'task', linsightSessionVersionId: 'sv1' });
    });

    it('changes nothing when the row is missing or the run already has a row', () => {
        const list = [row('q', true), taskRow('t', 'sv1')];
        expect(bindLiveTaskRow(list, 'other', 'r1')).toBe(list);
        const bound = bindLiveTaskRow(list, 'sv1', 'r1');
        expect(bindLiveTaskRow(bound, 'sv1', 'r1')).toBe(bound);
    });

    it('leaves a task row behind when the run ends, so the stored turn is shown again', () => {
        const bound = bindLiveTaskRow([taskRow('t', 'sv1')], 'sv1', 'r1');
        const frozen = freezeLiveRun(bound, run({ status: 'finished', text: 'done' }));
        expect(frozen[0].liveRunId).toBeUndefined();
        expect(frozen[0]).toMatchObject({ category: 'task', linsightSessionVersionId: 'sv1', text: 'done' });
    });

    it('keeps an ordinary live row an agent answer', () => {
        const shown = withLiveRun([row('live', false, { liveRunId: 'r1' })], run({ text: 'hi' }));
        expect(shown[0].category).toBe('agent_answer');
    });
});

it('reads the run record statuses that mean "not ended"', () => {
    expect(['not_started', 'in_progress', 'waiting_for_user_input'].map(isVersionInProgress)).toEqual([true, true, true]);
    expect(['completed', 'failed', 'terminated', 'sop_generation_failed', undefined].map(isVersionInProgress)).toEqual([
        false, false, false, false, false,
    ]);
});
