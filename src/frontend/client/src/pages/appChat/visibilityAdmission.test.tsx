import { render, screen, waitFor } from 'test/layout-test-utils';
import { getAssistantDetailApi, getChatHistoryApi, getFlowApi } from '~/api/apps';
import { checkResourceAction } from '~/api/permission';
import AppChat from './index';

const mockNavigate = jest.fn();
const mockToast = jest.fn();
jest.mock('react-router-dom', () => ({
  useParams: () => ({}), useNavigate: () => mockNavigate,
  BrowserRouter: ({ children }: { children: React.ReactNode }) => children,
}));
jest.mock('~/hooks/AuthContext', () => ({
  AuthContextProvider: ({ children }: { children: React.ReactNode }) => children,
}));
jest.mock('~/api/permission', () => ({ checkResourceAction: jest.fn() }));
jest.mock('~/api/apps', () => ({
  getAssistantDetailApi: jest.fn(), getChatHistoryApi: jest.fn(), getFlowApi: jest.fn(), postBuildInit: jest.fn(),
}));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/store', () => ({ __esModule: true, default: jest.requireActual('~/store/misc').default }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('@bisheng/ui', () => ({ Button: () => null }));
jest.mock('./ChatView', () => ({ __esModule: true, default: () => <div data-testid="app-chat-ready" /> }));

beforeEach(() => {
  jest.clearAllMocks();
  (getFlowApi as jest.Mock).mockResolvedValue({ data: { id: 'app-1', name: 'Workflow', flow_type: 10 } });
  (getAssistantDetailApi as jest.Mock).mockResolvedValue({ data: { id: 'app-1', name: 'Assistant', flow_type: 5 } });
  (getChatHistoryApi as jest.Mock).mockResolvedValue([]);
});

it.each([[10, 'workflow'], [5, 'assistant']])('opens visible app type %s', async (type, resourceType) => {
  (checkResourceAction as jest.Mock).mockResolvedValue({ allowed: true });
  render(<AppChat chatId="conversation-1" flowId="app-1" flowType={String(type)} />);
  await screen.findByTestId('app-chat-ready');
  expect(checkResourceAction).toHaveBeenCalledWith({ resource_type: resourceType, resource_id: 'app-1', action: 'visible' });
  expect(mockNavigate).not.toHaveBeenCalled();
});

it.each([10, 5])('rejects invisible app type %s before loading details or messages', async (type) => {
  (checkResourceAction as jest.Mock).mockResolvedValue({ allowed: false });
  render(<AppChat chatId="conversation-1" flowId="app-1" flowType={String(type)} />);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/apps', { replace: true }));
  expect(getFlowApi).not.toHaveBeenCalled();
  expect(getAssistantDetailApi).not.toHaveBeenCalled();
  expect(getChatHistoryApi).not.toHaveBeenCalled();
  expect(mockToast).toHaveBeenCalled();
});
