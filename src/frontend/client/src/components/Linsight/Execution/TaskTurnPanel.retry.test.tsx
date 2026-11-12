/** @jest-environment node */
import { renderToStaticMarkup } from 'react-dom/server';
import { TaskTurnPanel } from './TaskTurnPanel';

const mockContinue = jest.fn();
const mockGetLinsight = jest.fn();
let mockOnRetry: (() => void | Promise<void>) | undefined;
let mockShareToken: string | undefined;

jest.mock('~/api/linsight', () => ({ getLinsightSessionVersionList: jest.fn(), getLinsightTaskList: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/useAutoScroll', () => ({ useAutoScroll: jest.fn() }));
jest.mock('~/hooks/useLinsightManager', () => ({ useLinsightManager: () => ({
    continueConversation: mockContinue,
    getLinsight: mockGetLinsight,
    switchAndUpdateLinsight: jest.fn(),
    updateLinsight: jest.fn(),
}) }));
jest.mock('~/hooks/Websocket', () => ({ useLinsightWebSocket: () => ({ sendInput: jest.fn(), stop: jest.fn() }) }));
jest.mock('~/hooks/useLinsightQueuePolling', () => ({ useLinsightQueuePolling: jest.fn() }));
jest.mock('react-router-dom', () => ({ useParams: () => ({ token: mockShareToken }) }));
jest.mock('~/store/linsight', () => ({ SopStatus: { Running: 'running', Stoped: 'stoped', completed: 'completed' } }));
jest.mock('lucide-react', () => ({ OctagonX: () => null }));
jest.mock('~/components/ChatErrorCard', () => ({
    isTransientErrorType: (type?: string) => ['rate_limit', 'network_timeout', 'service_unavailable'].includes(type ?? ''),
    ChatErrorCard: ({ onRetry }: { onRetry?: () => void | Promise<void> }) => { mockOnRetry = onRetry; return null; },
}));
jest.mock('~/components/Linsight/Artifacts/ResultSection', () => ({ ResultSection: () => null }));
jest.mock('./AnswerFallback', () => ({ AnswerFallback: () => null }));
jest.mock('./BreathingRow', () => ({ BreathingRow: () => null }));
jest.mock('./ClarifyCard', () => ({ ClarifyCard: () => null }));
jest.mock('./ExecutionTimeline', () => ({ ExecutionTimeline: () => null }));
jest.mock('./QueueCard', () => ({ QueueCard: () => null }));
jest.mock('./ResultPanel', () => ({ ResultPanel: () => null }));
jest.mock('./TaskStepRow', () => ({ TaskStepRow: () => null }));
jest.mock('./taskTurnLoad', () => ({ useReportTaskTurnLoadFailed: () => jest.fn() }));

beforeEach(() => {
    jest.clearAllMocks();
    mockOnRetry = undefined;
    mockShareToken = undefined;
    mockContinue.mockResolvedValue(true);
    mockGetLinsight.mockReturnValue({
        status: 'stoped', question: 'Original question', taskError: 'failed',
        taskErrorInfo: { error_type: 'rate_limit' },
        tasks: [], sessionSteps: [], file_list: [], files: [], queueCount: 0,
    });
});

it.each(['rate_limit', 'network_timeout', 'service_unavailable'])('retries a recoverable %s through the existing task continuation', async (errorType) => {
    mockGetLinsight.mockReturnValue({ ...mockGetLinsight(), taskErrorInfo: { error_type: errorType } });
    renderToStaticMarkup(<TaskTurnPanel versionId="task-1" />);
    expect(mockOnRetry).toBeDefined();
    await mockOnRetry?.();
    expect(mockContinue).toHaveBeenCalledWith('task-1', 'Original question');
});

it('blocks duplicate clicks while the existing continuation request is pending', async () => {
    let resolve: ((accepted: boolean) => void) | undefined;
    mockContinue.mockImplementation(() => new Promise<boolean>((done) => { resolve = done; }));
    renderToStaticMarkup(<TaskTurnPanel versionId="task-1" />);
    const first = mockOnRetry?.();
    await mockOnRetry?.();
    expect(mockContinue).toHaveBeenCalledTimes(1);
    resolve?.(true);
    await first;
});

it.each(['auth_error', 'content_filter', 'quota_exhausted', 'credit_exhausted', 'context_overflow', 'unknown'])('does not offer a blind retry for %s', (errorType) => {
    mockGetLinsight.mockReturnValue({ ...mockGetLinsight(), taskErrorInfo: { error_type: errorType } });
    renderToStaticMarkup(<TaskTurnPanel versionId="task-1" />);
    expect(mockOnRetry).toBeUndefined();
});

it('keeps the share/read-only carrier non-interactive', () => {
    renderToStaticMarkup(<TaskTurnPanel versionId="task-1" readOnly />);
    expect(mockOnRetry).toBeUndefined();
    expect(mockContinue).not.toHaveBeenCalled();
});

it('does not offer task continuation on a share route without an explicit readOnly prop', () => {
    mockShareToken = 'shared-conversation';
    renderToStaticMarkup(<TaskTurnPanel versionId="task-1" />);
    expect(mockOnRetry).toBeUndefined();
    expect(mockContinue).not.toHaveBeenCalled();
});
