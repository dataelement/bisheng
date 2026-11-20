/**
 * F004 (T050): the question card of a run.
 * It reads the pending question from the run store and answers through the
 * send entry (AC-20, AC-21).
 */
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { useRunStore, type RunEvent } from '~/store/runStore';
import { useRunAwaitingAnswer } from '~/components/Chat/hooks/useTaskWorkspaceState';
import { RunClarifyCard, runQuestionToClarifyData } from './ClarifyCard';
import { parseClarifyRequest } from './stepUtils';

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
}));
jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy({}, { get: () => () => null }),
    Filled: new Proxy({}, { get: () => () => null }),
    Colored: new Proxy({}, { get: () => () => null }),
}));
// useTaskWorkspaceState.ts pulls the workspace panel tree; only the small
// run hook of that module is under test here.
jest.mock('react-activation', () => ({ useUnactivate: jest.fn() }));
jest.mock('~/components/Linsight/Artifacts/useWorkspacePanel', () => ({ useWorkspacePanel: jest.fn() }));
jest.mock('~/components/Linsight/Artifacts/useCompareTransitionFreeze', () => ({
    useCompareTransitionFreeze: jest.fn(),
}));
jest.mock('~/components/Linsight/Artifacts/artifactUtils', () => ({}));
jest.mock('~/hooks/useLinsightManager', () => ({ useLinsightManager: jest.fn() }));
jest.mock('~/store/linsight', () => ({ SopStatus: {} }));
jest.mock('~/components/Chat/attachments/collectChatAttachments', () => ({ collectChatAttachments: jest.fn() }));

const CID = 'conv-1';
const RUN = 'run-1';

const ev = (type: string, data: unknown, id: string): RunEvent =>
    ({ type, data, run_id: RUN, id }) as unknown as RunEvent;

function ask(callId = 'call-1') {
    act(() => {
        useRunStore.getState().applyEvent(CID, ev('run_started', {}, '1-0'));
        useRunStore.getState().applyEvent(
            CID,
            ev(
                'ask_user',
                {
                    call_id: callId,
                    reason: 'The quote has no delivery date',
                    questions: [{ question: 'Which one applies?', options: ['30 days by contract', 'Mark as pending'] }],
                },
                `${Date.now()}-1`,
            ),
        );
    });
}

beforeEach(() => {
    act(() => useRunStore.getState().resetConversation(CID));
});

describe('runQuestionToClarifyData', () => {
    it('maps an ask_user payload to the shape the card parses', () => {
        const data = runQuestionToClarifyData({
            call_id: 'c1',
            reason: 'why',
            questions: [
                { question: 'Q1', options: ['a', 'b'], multiple: true, id: 'q-a' },
                { question: 'Q2' },
            ],
        });
        const parsed = parseClarifyRequest(data);
        expect(parsed.taskId).toBe('');
        expect(parsed.callReason).toBe('why');
        expect(parsed.questions).toEqual([
            { id: 'q-a', question: 'Q1', options: ['a', 'b'], multiple: true },
            { id: 'q_1', question: 'Q2', options: [], multiple: false },
        ]);
    });
});

describe('RunClarifyCard', () => {
    it('shows the pending question of the run store and answers through the send entry', async () => {
        const onSend = jest.fn().mockResolvedValue(true);
        render(<RunClarifyCard conversationId={CID} onSend={onSend} />);
        expect(screen.queryByText('Which one applies?')).toBeNull();

        ask();
        expect(screen.getByText('Which one applies?')).toBeTruthy();

        fireEvent.click(screen.getByText('30 days by contract'));
        await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
        expect(onSend).toHaveBeenCalledWith('30 days by contract');
    });

    it('disappears when the run continues', () => {
        render(<RunClarifyCard conversationId={CID} onSend={jest.fn()} />);
        ask();
        act(() => {
            useRunStore
                .getState()
                .applySendResult(CID, { run_id: RUN, disposition: 'started', message_id: 'm1' });
        });
        expect(screen.queryByText('Which one applies?')).toBeNull();
    });

    it('disappears when the run is stopped', () => {
        render(<RunClarifyCard conversationId={CID} onSend={jest.fn()} />);
        ask();
        act(() => useRunStore.getState().applyEvent(CID, ev('run_stopped', {}, `${Date.now() + 5}-0`)));
        expect(screen.queryByText('Which one applies?')).toBeNull();
        expect(useRunStore.getState().conversations[CID]?.run?.status).toBe('stopped');
    });

    it('can be answered again after a rejected send', async () => {
        const onSend = jest.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
        render(<RunClarifyCard conversationId={CID} onSend={onSend} />);
        ask();
        fireEvent.click(screen.getByText('Mark as pending'));
        await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
        await act(async () => {});
        fireEvent.click(screen.getByText('Mark as pending'));
        await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    });

    it('renders nothing without a conversation', () => {
        ask();
        const { container } = render(<RunClarifyCard conversationId="" onSend={jest.fn()} />);
        expect(container.innerHTML).toBe('');
    });
});

describe('useRunAwaitingAnswer', () => {
    it('is true only while the run waits for an answer', () => {
        const { result } = renderHook(() => useRunAwaitingAnswer(CID));
        expect(result.current).toBe(false);
        ask();
        expect(result.current).toBe(true);
        act(() => useRunStore.getState().applyEvent(CID, ev('ask_user_answered', {}, `${Date.now() + 5}-0`)));
        expect(result.current).toBe(false);
    });

    it('is false for an empty conversation id', () => {
        ask();
        expect(renderHook(() => useRunAwaitingAnswer('')).result.current).toBe(false);
    });
});
