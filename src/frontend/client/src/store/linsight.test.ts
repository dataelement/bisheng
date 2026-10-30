// eslint-disable-next-line no-restricted-imports -- test drives the existing selector; adds no new Recoil state
import { snapshot_UNSTABLE } from 'recoil';
import {
    conversationTaskRunningState,
    isLinsightParked,
    LinsightInfo,
    linsightMapState,
    SopStatus,
} from './linsight';

// isLinsightParked detects a session waiting on an UNANSWERED ask_user clarify,
// the signal that drives the sidebar spinner OFF (a parked session is not
// executing — it is waiting for the user). Mirrors findPendingUserInput's
// call_user_input + is_completed contract.
describe('store/linsight — isLinsightParked', () => {
    it('returns false for an empty / fieldless info', () => {
        expect(isLinsightParked({})).toBe(false);
        expect(isLinsightParked({ sessionSteps: [], tasks: [] })).toBe(false);
    });

    it('returns false while only thinking / tool steps stream (real execution)', () => {
        expect(
            isLinsightParked({
                sessionSteps: [
                    { step_type: 'thinking', output: '…' },
                    { step_type: 'tool', name: 'web_search' },
                ],
            }),
        ).toBe(false);
    });

    it('returns true on an UNANSWERED session-level call_user_input (live park)', () => {
        expect(
            isLinsightParked({
                sessionSteps: [
                    { step_type: 'thinking', output: '…' },
                    { step_type: 'call_user_input', is_completed: false },
                ],
            }),
        ).toBe(true);
    });

    it('returns false once the clarify is answered (resumed, not parked)', () => {
        expect(
            isLinsightParked({
                sessionSteps: [{ step_type: 'call_user_input', is_completed: true, user_input: '中文' }],
            }),
        ).toBe(false);
    });

    it('detects a park in a task history', () => {
        expect(
            isLinsightParked({
                tasks: [{ history: [{ step_type: 'call_user_input', is_completed: false }] }],
            }),
        ).toBe(true);
    });

    it('detects a park in a nested subtask (children) history', () => {
        expect(
            isLinsightParked({
                tasks: [
                    {
                        history: [{ step_type: 'thinking' }],
                        children: [{ history: [{ step_type: 'call_user_input', is_completed: false }] }],
                    },
                ],
            }),
        ).toBe(true);
    });

    it('returns false when every task-level clarify is answered', () => {
        expect(
            isLinsightParked({
                tasks: [
                    { history: [{ step_type: 'call_user_input', is_completed: true }] },
                    { history: [{ step_type: 'thinking' }], children: [] },
                ],
            }),
        ).toBe(false);
    });
});

// The sidebar selector must not retain old versions of linsightMapState: the WS
// pump publishes a new map per streamed frame, and a keep-all cache held every
// one of them (quadratic memory growth on long tasks).
describe('store/linsight — conversationTaskRunningState cache', () => {
    // Recoil deep-freezes atom values in development, so the read counter lives
    // outside the map instead of on it.
    const reads = new WeakMap<Map<string, LinsightInfo>, number>();
    class CountingMap extends Map<string, LinsightInfo> {
        values() {
            reads.set(this, (reads.get(this) ?? 0) + 1);
            return super.values();
        }
    }

    const makeMap = (status: string) =>
        new CountingMap([['svid', { session_id: 'conv-1', status } as LinsightInfo]]);

    const evaluate = (map: Map<string, LinsightInfo>) =>
        snapshot_UNSTABLE(({ set }) => set(linsightMapState, map))
            .getLoadable(conversationTaskRunningState('conv-1'))
            .getValue();

    it('reflects the current map value', () => {
        expect(evaluate(makeMap(SopStatus.Running))).toBe(true);
        expect(evaluate(makeMap('completed'))).toBe(false);
    });

    it('keeps only the most recent dependency value in its cache', () => {
        const first = makeMap(SopStatus.Running);
        const second = makeMap(SopStatus.Running);
        evaluate(first);
        evaluate(second);
        evaluate(first);
        // A keep-all cache would still hold `first` and skip the second read.
        expect(reads.get(first)).toBe(2);
    });
});
