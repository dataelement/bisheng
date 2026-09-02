/** @jest-environment node */

import { renderToStaticMarkup } from 'react-dom/server';
import { TaskTurnPanel } from './TaskTurnPanel';

const mockContinueConversation = jest.fn();
const mockGetLinsight = jest.fn();
let mockOnRetry: (() => void) | undefined;
let mockOnSwitchModel: ((modelId: string) => void | Promise<void>) | undefined;
let mockSwitchModelOptions: Array<{ id: string | number }> | undefined;

jest.mock('~/api/linsight', () => ({
    getLinsightSessionVersionList: jest.fn(),
    getLinsightTaskList: jest.fn(),
}));

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock('~/hooks/queries/data-provider', () => ({
    useGetBsConfig: () => ({
        data: {
            models: [
                { id: '18', name: 'busy-model', rateLimitState: 'busy' },
                { id: '22', name: 'available-model', displayName: 'Available Model' },
                { id: '23', name: 'recovering-model', rateLimitState: 'recovering' },
            ],
        },
    }),
}));

jest.mock('~/Providers', () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
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
    ChatErrorCard: ({
        onRetry,
        onSwitchModel,
        switchModelOptions,
    }: {
        onRetry?: () => void;
        onSwitchModel?: (modelId: string) => void | Promise<void>;
        switchModelOptions?: Array<{ id: string | number }>;
    }) => {
        mockOnRetry = onRetry;
        mockOnSwitchModel = onSwitchModel;
        mockSwitchModelOptions = switchModelOptions;
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
        mockOnSwitchModel = undefined;
        mockSwitchModelOptions = undefined;
        mockContinueConversation.mockResolvedValue(true);
        mockGetLinsight.mockReturnValue({
            status: 'stoped',
            question: 'Analyze gold trend',
            taskError: 'rate limited',
            taskErrorInfo: {
                error_type: 'rate_limit',
                model_id: '18',
                rate_limit_state: 'busy',
            },
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
        expect(mockOnSwitchModel).toBeUndefined();
    });

    it('switches and retries through the same continuation flow', async () => {
        const onModelChange = jest.fn();
        renderToStaticMarkup(
            <TaskTurnPanel versionId="version-1" onModelChange={onModelChange} />,
        );

        expect(mockSwitchModelOptions?.map((model) => model.id)).toEqual(['22']);
        await mockOnSwitchModel?.('22');

        expect(mockContinueConversation).toHaveBeenCalledWith(
            'version-1',
            'Analyze gold trend',
            '22',
        );
        expect(onModelChange).toHaveBeenCalledWith('22', 'Available Model');
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
        expect(mockOnSwitchModel).toBeUndefined();
    });
});
