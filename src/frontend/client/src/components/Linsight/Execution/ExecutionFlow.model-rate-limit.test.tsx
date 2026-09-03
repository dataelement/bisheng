/** @jest-environment node */

import { renderToStaticMarkup } from 'react-dom/server';
import { ExecutionFlow } from './ExecutionFlow';

const mockContinueConversation = jest.fn();
let mockReadOnly = false;
let mockOnRetry: (() => void | Promise<void>) | undefined;
let mockOnSwitchModel: ((modelId: string) => void | Promise<void>) | undefined;
let mockSwitchModelOptions: Array<{ id: string | number }> | undefined;

const task = {
    id: 'version-1',
    session_id: 'chat-1',
    model: '18',
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
    history: [],
    queueCount: 0,
};

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock('~/hooks/queries/data-provider', () => ({
    useGetBsConfig: () => ({
        data: {
            models: [
                { id: '18', name: 'busy-model', rateLimitState: 'busy' },
                { id: '22', name: 'available-model' },
                { id: '23', name: 'recovering-model', rateLimitState: 'recovering' },
            ],
        },
    }),
}));

jest.mock('~/Providers', () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock('~/hooks/useLinsightManager', () => ({
    useLinsightManager: () => ({
        continueConversation: mockContinueConversation,
        getLinsight: () => task,
        updateLinsight: jest.fn(),
    }),
}));

jest.mock('~/hooks/Websocket', () => ({
    useLinsightWebSocket: () => ({ stop: jest.fn(), sendInput: jest.fn() }),
}));

jest.mock('~/hooks/useLinsightQueuePolling', () => ({
    useLinsightQueuePolling: jest.fn(),
}));

jest.mock('~/hooks/useAutoScroll', () => ({
    useAutoScroll: jest.fn(),
}));

jest.mock('~/components/ChatErrorCard', () => ({
    ChatErrorCard: ({
        onRetry,
        onSwitchModel,
        switchModelOptions,
    }: {
        onRetry?: () => void | Promise<void>;
        onSwitchModel?: (modelId: string) => void | Promise<void>;
        switchModelOptions?: Array<{ id: string | number }>;
    }) => {
        mockOnRetry = onRetry;
        mockOnSwitchModel = onSwitchModel;
        mockSwitchModelOptions = switchModelOptions;
        return null;
    },
}));

jest.mock('~/components/Linsight/Input/TaskModeInput', () => ({
    TaskModeInput: () => null,
}));

jest.mock('~/components/Linsight/Artifacts/FilePreviewPanel', () => ({ FilePreviewPanel: () => null }));
jest.mock('~/components/Linsight/Artifacts/ResultSection', () => ({ ResultSection: () => null }));
jest.mock('~/components/Linsight/Artifacts/WorkspaceDrawer', () => ({ WorkspaceDrawer: () => null }));
jest.mock('lucide-react', () => ({ OctagonX: () => null }));
jest.mock('./BreathingRow', () => ({ BreathingRow: () => null }));
jest.mock('./ClarifyCard', () => ({ ClarifyCard: () => null }));
jest.mock('./ConversationRound', () => ({ ConversationRound: () => null }));
jest.mock('./ExecutionTimeline', () => ({ ExecutionTimeline: () => null }));
jest.mock('./LegacySopRow', () => ({ LegacySopRow: () => null }));
jest.mock('./QueueCard', () => ({ QueueCard: () => null }));
jest.mock('./ResultPanel', () => ({ ResultPanel: () => null }));
jest.mock('./TaskPanel', () => ({ TaskPanel: () => null }));
jest.mock('./TaskStepRow', () => ({ TaskStepRow: () => null }));

const artifactsPanel = {
    workspaceOpen: false,
    setWorkspaceOpen: jest.fn(),
    previewFile: null,
    openPreview: jest.fn(),
    closePreview: jest.fn(),
    fromWorkspace: false,
    backToWorkspace: jest.fn(),
};

describe('ExecutionFlow model rate-limit recovery', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockReadOnly = false;
        mockOnRetry = undefined;
        mockOnSwitchModel = undefined;
        mockSwitchModelOptions = undefined;
        mockContinueConversation.mockResolvedValue(true);
    });

    function renderFlow() {
        renderToStaticMarkup(
            <ExecutionFlow
                versionId="version-1"
                readOnly={mockReadOnly}
                artifactsPanel={artifactsPanel as never}
            />,
        );
    }

    it('offers retry and available replacement models in the editable carrier', async () => {
        renderFlow();

        expect(mockOnRetry).toBeDefined();
        expect(mockSwitchModelOptions?.map((model) => model.id)).toEqual(['22']);
        await mockOnSwitchModel?.('22');

        expect(mockContinueConversation).toHaveBeenCalledWith(
            'version-1',
            'Analyze gold trend',
            '22',
        );
    });

    it('keeps the historical read-only carrier non-interactive', () => {
        mockReadOnly = true;
        renderFlow();

        expect(mockOnRetry).toBeUndefined();
        expect(mockOnSwitchModel).toBeUndefined();
    });
});
