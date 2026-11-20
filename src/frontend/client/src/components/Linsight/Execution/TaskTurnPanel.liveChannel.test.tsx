/**
 * F004 (T061): the inline task turn with and without its live channel.
 * With the channel (a carrier that follows no run events) the panel drives the
 * task WebSocket and the clarify card. Without it (the conversation page) it
 * only shows what is stored.
 */
import { act, render } from '@testing-library/react';
import { useRunStore, type RunEvent } from '~/store/runStore';
import { TaskTurnRetryContext } from '~/components/Chat/runPageContext';
import { TaskTurnPanel } from './TaskTurnPanel';

const mockGetLinsight = jest.fn();
const mockLegacyRetry = jest.fn();
const mockReconcile = jest.fn();
const mockSocketVersions: string[] = [];
const mockSendInput = jest.fn();
let mockClarifySubmit: ((taskId: string, answer: string) => void) | undefined;
let mockOnRetry: (() => void | Promise<void>) | undefined;
let mockTransient = true;
let mockQueueCards = 0;
const mockQueuePolling = jest.fn();

jest.mock('~/api/linsight', () => ({ getLinsightSessionVersionList: jest.fn(), getLinsightTaskList: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/useAutoScroll', () => ({ useAutoScroll: jest.fn() }));
jest.mock('~/hooks/useLinsightManager', () => ({ useLinsightManager: () => ({
    retryConversation: mockLegacyRetry,
    getLinsight: mockGetLinsight,
    switchAndUpdateLinsight: jest.fn(),
    updateLinsight: jest.fn(),
    reconcileLinsightFromServer: mockReconcile,
}) }));
jest.mock('~/hooks/Websocket', () => ({ useLinsightWebSocket: (versionId: string) => {
    mockSocketVersions.push(versionId);
    return { sendInput: mockSendInput, stop: jest.fn() };
} }));
jest.mock('~/hooks/useLinsightQueuePolling', () => ({
    useLinsightQueuePolling: (...args: unknown[]) => mockQueuePolling(...args),
}));
jest.mock('react-router-dom', () => ({ useParams: () => ({}) }));
jest.mock('~/store/linsight', () => ({
    SopStatus: { NotStarted: 'not_started', Running: 'running', Stoped: 'stoped', completed: 'completed' },
}));
jest.mock('lucide-react', () => ({ OctagonX: () => null }));
jest.mock('~/components/ChatErrorCard', () => ({
    isTransientErrorType: () => mockTransient,
    ChatErrorCard: ({ onRetry }: { onRetry?: () => void }) => { mockOnRetry = onRetry; return null; },
}));
jest.mock('~/components/Linsight/Artifacts/ResultSection', () => ({ ResultSection: () => null }));
jest.mock('./AnswerFallback', () => ({ AnswerFallback: () => null }));
jest.mock('./BreathingRow', () => ({ BreathingRow: () => null }));
jest.mock('./ClarifyCard', () => ({
    ClarifyCard: ({ onSubmit }: { onSubmit: (taskId: string, answer: string) => void }) => {
        mockClarifySubmit = onSubmit;
        return null;
    },
}));
jest.mock('./ExecutionTimeline', () => ({ ExecutionTimeline: () => null }));
jest.mock('./QueueCard', () => ({ QueueCard: () => { mockQueueCards += 1; return null; } }));
jest.mock('./ResultPanel', () => ({ ResultPanel: () => null }));
jest.mock('./TaskStepRow', () => ({ TaskStepRow: () => null }));
jest.mock('./taskTurnLoad', () => ({ useReportTaskTurnLoadFailed: () => jest.fn() }));
jest.mock('./stepUtils', () => ({
    findPendingUserInput: (steps: Array<{ pending?: boolean }>) => steps.find((s) => s.pending) ?? null,
    hasRenderableTimeline: () => false,
    isTaskRunning: () => false,
    isTaskStarted: () => true,
    splitSessionPseudoTask: (tasks: unknown[], sessionSteps: unknown[]) => ({ tasks, sessionSteps }),
}));

const parked = { status: 'running', question: 'q', tasks: [], sessionSteps: [{ pending: true }], file_list: [], queueCount: 0 };
const queued = { status: 'running', question: 'q', tasks: [], sessionSteps: [], file_list: [], queueCount: 2 };
const failed = { ...parked, status: 'stoped', sessionSteps: [], taskError: 'boom', taskErrorInfo: { error_type: 'rate_limit' } };

beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    mockSocketVersions.length = 0;
    mockClarifySubmit = undefined;
    mockOnRetry = undefined;
    mockTransient = true;
    mockQueueCards = 0;
    mockReconcile.mockResolvedValue(false);
    act(() => useRunStore.setState({ conversations: {} }));
});
afterEach(() => {
    jest.useRealTimers();
});

describe('with the live channel', () => {
    it('drives the task WebSocket and answers a question through it', () => {
        mockGetLinsight.mockReturnValue(parked);
        render(<TaskTurnPanel versionId="sv1" conversationId="c1" />);
        expect(mockSocketVersions).toEqual(['sv1']);
        mockClarifySubmit?.('task-9', 'my answer');
        expect(mockSendInput).toHaveBeenCalledWith({ task_id: 'task-9', user_input: 'my answer', files: [] });
        act(() => { jest.advanceTimersByTime(20000); });
        expect(mockReconcile).not.toHaveBeenCalled();
    });

    it('keeps the queue card, queue polling and the retry action', () => {
        mockGetLinsight.mockReturnValue(queued);
        render(<TaskTurnPanel versionId="sv1" conversationId="c1" />);
        expect(mockQueueCards).toBe(1);
        expect(mockQueuePolling).toHaveBeenCalledWith('sv1', true);
        mockGetLinsight.mockReturnValue(failed);
        render(<TaskTurnPanel versionId="sv1" conversationId="c1" />);
        expect(mockOnRetry).toBeDefined();
    });
});

describe('without the live channel (conversation page)', () => {
    it('opens no task WebSocket and never offers the legacy answer, cancel or retry', () => {
        mockGetLinsight.mockReturnValue(parked);
        render(<TaskTurnPanel versionId="sv1" conversationId="c1" liveChannel={false} />);
        expect(mockSocketVersions).toEqual(['']);
        expect(mockClarifySubmit).toBeUndefined();
        mockGetLinsight.mockReturnValue(queued);
        render(<TaskTurnPanel versionId="sv1" conversationId="c1" liveChannel={false} />);
        expect(mockQueueCards).toBe(0);
        expect(mockQueuePolling).toHaveBeenLastCalledWith('sv1', false);
        mockGetLinsight.mockReturnValue(failed);
        render(<TaskTurnPanel versionId="sv1" conversationId="c1" liveChannel={false} />);
        expect(mockOnRetry).toBeUndefined();
        expect(mockSendInput).not.toHaveBeenCalled();
    });

    describe('retry of a failed turn (design §7 item 15)', () => {
        const renderWithRetry = (retry: jest.Mock | null, turn: unknown = failed) => {
            mockGetLinsight.mockReturnValue(turn);
            return render(
                <TaskTurnRetryContext.Provider value={retry}>
                    <TaskTurnPanel versionId="sv1" conversationId="c1" liveChannel={false} />
                </TaskTurnRetryContext.Provider>,
            );
        };

        it('sends the question of the turn again through the page send entry, not the task channel', async () => {
            const retry = jest.fn().mockResolvedValue(true);
            renderWithRetry(retry);
            expect(mockOnRetry).toBeDefined();
            await act(async () => { await mockOnRetry?.(); });
            expect(retry).toHaveBeenCalledTimes(1);
            expect(retry).toHaveBeenCalledWith('q');
            expect(mockLegacyRetry).not.toHaveBeenCalled();
            expect(mockSocketVersions.every((id) => id === '')).toBe(true);
        });

        it('ignores a second click while the first retry is being sent', async () => {
            let finish: ((accepted: boolean) => void) | undefined;
            const retry = jest.fn(() => new Promise<boolean>((resolve) => { finish = resolve; }));
            renderWithRetry(retry);
            let first: void | Promise<void>;
            act(() => { first = mockOnRetry?.(); });
            await act(async () => { await mockOnRetry?.(); });
            expect(retry).toHaveBeenCalledTimes(1);
            await act(async () => { finish?.(true); await first; });
        });

        it('is not offered while the conversation has a run in progress', () => {
            act(() => {
                useRunStore.getState().applyEvent('c1', { type: 'run_started', run_id: 'r1', data: {} } as RunEvent, '1-1');
            });
            renderWithRetry(jest.fn());
            expect(mockOnRetry).toBeUndefined();
            act(() => {
                useRunStore.getState().applyEvent('c1', { type: 'run_stopped', run_id: 'r1', data: {} } as RunEvent, '1-2');
            });
            expect(mockOnRetry).toBeDefined();
        });

        it('is not offered for an error that a retry cannot fix, or for a turn without a question', () => {
            mockTransient = false;
            renderWithRetry(jest.fn()).unmount();
            expect(mockOnRetry).toBeUndefined();
            mockTransient = true;
            renderWithRetry(jest.fn(), { ...failed, question: '' });
            expect(mockOnRetry).toBeUndefined();
        });

        it('keeps the legacy retry on a page with the live channel, even inside a retry provider', async () => {
            const retry = jest.fn();
            mockGetLinsight.mockReturnValue(failed);
            render(
                <TaskTurnRetryContext.Provider value={retry}>
                    <TaskTurnPanel versionId="sv1" conversationId="c1" />
                </TaskTurnRetryContext.Provider>,
            );
            await act(async () => { await mockOnRetry?.(); });
            expect(mockLegacyRetry).toHaveBeenCalledWith('sv1', 'q');
            expect(retry).not.toHaveBeenCalled();
        });
    });

    it('asks the server for the final state of a turn stored as running once no run is in progress', async () => {
        mockGetLinsight.mockReturnValue(queued);
        render(<TaskTurnPanel versionId="sv1" conversationId="c1" liveChannel={false} />);
        await act(async () => { jest.advanceTimersByTime(0); });
        expect(mockReconcile).toHaveBeenCalledWith('sv1');
        await act(async () => { jest.advanceTimersByTime(2000); });
        expect(mockReconcile).toHaveBeenCalledTimes(2);
    });

    it('waits while the conversation has a run in progress, and leaves an ended turn alone', async () => {
        act(() => {
            useRunStore.getState().applyEvent('c1', { type: 'run_started', run_id: 'r1', data: {} } as RunEvent, '1-1');
        });
        mockGetLinsight.mockReturnValue(queued);
        const first = render(<TaskTurnPanel versionId="sv1" conversationId="c1" liveChannel={false} />);
        await act(async () => { jest.advanceTimersByTime(20000); });
        expect(mockReconcile).not.toHaveBeenCalled();
        act(() => {
            useRunStore.getState().applyEvent('c1', { type: 'run_finished', run_id: 'r1', data: {} } as RunEvent, '1-2');
        });
        await act(async () => { jest.advanceTimersByTime(0); });
        expect(mockReconcile).toHaveBeenCalledTimes(1);

        first.unmount();
        mockReconcile.mockClear();
        mockGetLinsight.mockReturnValue({ ...failed, taskError: '' });
        render(<TaskTurnPanel versionId="sv2" conversationId="c2" liveChannel={false} />);
        await act(async () => { jest.advanceTimersByTime(20000); });
        expect(mockReconcile).not.toHaveBeenCalled();
    });
});
