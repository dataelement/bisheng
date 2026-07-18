import { isLinsightParked } from './linsight';

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
