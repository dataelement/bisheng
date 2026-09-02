/** @jest-environment node */

import { renderToStaticMarkup } from 'react-dom/server';
import { TaskTurnPanel } from './TaskTurnPanel';

const mockContinueConversation = jest.fn();
const mockGetLinsight = jest.fn();
let mockOnRetry: (() => void) | undefined;

jest.mock('~/api/linsight', () => ({
    getLinsightSessionVersionList: jest.fn(),
    getLinsightTaskList: jest.fn(),
}));

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock('~/hooks/useAutoScroll', () => ({
    useAutoScroll: jest.fn(),
}));

jest.mock('~/hooks/useLinsightManager', () => ({
    useLinsightManager: () => ({
        continueConversation: mockContinueConversation,
        getLinsight: mockGetLinsight,
        switchAndUpdateLinsight: jest.fn(),
        updateLinsight: jest.fn(),
    }),
}));

jest.mock('~/hooks/useLinsightQueuePolling', () => ({
    useLinsightQueuePolling: jest.fn(),
}));

jest.mock('~/hooks/Websocket', () => ({
    useLinsightWebSocket: () => ({
        sendInput: jest.fn(),
        stop: jest.fn(),
    }),
}));

jest.mock('react-router-dom', () => ({
    useParams: () => ({}),
}));

jest.mock('lucide-react', () => ({
    OctagonX: () => null,
}));

jest.mock('~/components/ChatErrorCard', () => ({
    ChatErrorCard: ({ onRetry }: { onRetry?: () => void }) => {
        mockOnRetry = onRetry;
        return null;
    },
}));

jest.mock('~/components/Linsight/Artifacts/ResultSection', () => ({
    ResultSection: () => null,
}));

jest.mock('./BreathingRow', () => ({ BreathingRow: () => null }));
jest.mock('./ClarifyCard', () => ({ ClarifyCard: () => null }));
jest.mock('./ExecutionTimeline', () => ({ ExecutionTimeline: () => null }));
jest.mock('./QueueCard', () => ({ QueueCard: () => null }));
jest.mock('./ResultPanel', () => ({ ResultPanel: () => null }));
jest.mock('./TaskStepRow', () => ({ TaskStepRow: () => null }));

describe('TaskTurnPanel model rate-limit retry', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockOnRetry = undefined;
        mockGetLinsight.mockReturnValue({
            status: 'stoped',
            question: 'Analyze gold trend',
            taskError: 'rate limited',
            taskErrorInfo: { error_type: 'rate_limit' },
            tasks: [],
            sessionSteps: [],
            file_list: [],
            files: [],
            queueCount: 0,
        });
    });

    it('retries the failed task through the existing continuation flow', () => {
        renderToStaticMarkup(<TaskTurnPanel versionId="version-1" />);

        expect(mockOnRetry).toBeDefined();
        mockOnRetry?.();

        expect(mockContinueConversation).toHaveBeenCalledTimes(1);
        expect(mockContinueConversation).toHaveBeenCalledWith('version-1', 'Analyze gold trend');
    });

    it('does not expose retry in a read-only task turn', () => {
        renderToStaticMarkup(<TaskTurnPanel versionId="version-1" readOnly />);

        expect(mockOnRetry).toBeUndefined();
    });

    it('does not change retry behavior for other task errors', () => {
        mockGetLinsight.mockReturnValue({
            status: 'stoped',
            question: 'Analyze gold trend',
            taskError: 'service unavailable',
            taskErrorInfo: { error_type: 'service_unavailable' },
            tasks: [],
            sessionSteps: [],
            file_list: [],
            files: [],
            queueCount: 0,
        });

        renderToStaticMarkup(<TaskTurnPanel versionId="version-1" />);

        expect(mockOnRetry).toBeUndefined();
    });
});
