import React, { useCallback as mockUseCallback, useState as mockUseState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import ChatView from './ChatView';
import { parkChatAsk } from './chatAskHandoff';

const mockLanding = jest.fn();
const mockSend = jest.fn<Promise<boolean>, [string]>();
const mockNoop = () => undefined;
const mockConfig = { models: [{ id: '1', name: 'Alpha', displayName: 'Alpha' }] };
let mockConfigReady = false;
let mockStreaming = false;
const mockLinsightMap = new Map();

jest.mock('~/components/ApiRequestFailure', () => ({ ApiRequestFailure: () => null }));
jest.mock('./attachments/collectChatAttachments', () => ({ collectChatAttachments: () => [] }));
jest.mock('react-activation', () => ({ useActivate: () => undefined, useUnactivate: () => undefined }));
jest.mock('recoil', () => ({
  useRecoilState: (key: string) => jest.requireActual('react').useState(
    key === 'task' ? false : key === 'model' ? { id: 1, name: 'Alpha' } : '',
  ),
}));
jest.mock('~/store', () => ({ __esModule: true, default: { chatModel: 'model', searchType: 'search' } }));
jest.mock('~/store/linsight', () => ({
  taskModeState: 'task',
  SopStatus: { NotStarted: 'not_started', SopGenerating: 'generating', SopGenerated: 'generated', Running: 'running' },
}));
jest.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: null }) }));
jest.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: { id: 'tester', plugins: [] } }) }));
jest.mock('~/hooks/queries/data-provider', () => ({
  useGetBsConfig: () => ({ data: mockConfigReady ? mockConfig : undefined }),
  useGetOrgToolList: () => ({ data: [], isSuccess: false }),
}));
jest.mock('~/hooks/queries/queries', () => ({ useGetWorkbenchModelsQuery: () => ({ data: {} }) }));
jest.mock('~/hooks/useLocalize', () => ({ __esModule: true, default: () => (key: string) => key }));
jest.mock('~/hooks/usePrefersMobileLayout', () => ({ __esModule: true, default: () => true }));
jest.mock('~/hooks/useMediaQuery', () => ({ __esModule: true, default: () => true }));
jest.mock('~/hooks/useSessionPresence', () => ({ useSessionPresence: () => ({ ensureLeaseId: mockNoop }) }));
jest.mock('~/hooks/useChatModelResolution', () => ({
  readAdminDefaultModelId: () => undefined, moveConversationModel: () => undefined,
  useChatModelResolution: () => ({ persistPick: mockNoop }),
}));
jest.mock('~/hooks/useMessageSelection', () => ({
  useExitSelectionOnChatChange: () => undefined,
  useMessageSelection: () => ({ state: { active: false }, getSelectedIds: mockNoop, exitSelectionMode: mockNoop }),
}));
jest.mock('~/hooks/useLinsightManager', () => ({
  useLinsightManager: () => ({ getLinsight: mockNoop, updateLinsight: mockNoop, linsightMap: mockLinsightMap }),
}));
jest.mock('~/hooks/useAiChat', () => ({
  __esModule: true,
  default: () => {
    const [selectedOrgKbs, setSelectedOrgKbs] = mockUseState<{ id: string; name: string; type: string }[]>([]);
    const [messages, setMessages] = mockUseState<{ text: string; messageId: string }[]>([]);
    const sendMessage = mockUseCallback(async (text: string) => {
      const accepted = await mockSend(text);
      if (accepted) setMessages([{ text, messageId: 'question' }]);
      return accepted;
    }, []);
    return { selectedOrgKbs, setSelectedOrgKbs, messages, sendMessage,
      conversationId: 'new', isStreaming: mockStreaming,
      isLoading: false, isClearing: false, stopGenerating: mockNoop };
  },
}));
jest.mock('~/components/Chat/TaskInviteQuota', () => ({
  useTaskInviteQuota: () => ({ bar: null, dialog: null, allowSend: () => true }),
}));
jest.mock('~/components/Chat/Messages/Content/useCitationReferencePanel', () => ({
  useCitationReferencePanel: () => ({ citationPanelElement: null, closeCitationPanel: mockNoop }),
}));
jest.mock('~/components/Linsight/Artifacts/useWorkspacePanel', () => ({
  useWorkspacePanel: () => ({ open: false, fullscreen: false, comparing: false,
    closeWorkspace: mockNoop, setFullscreen: mockNoop }),
}));
jest.mock('~/components/Linsight/Artifacts/useCompareTransitionFreeze', () => ({
  useCompareTransitionFreeze: () => ({ rowRef: null, chatRef: null }),
}));
jest.mock('~/components/Linsight/Artifacts/artifactUtils', () => ({
  collectConversationWorkspaceFiles: () => [], getWorkspaceLoadState: () => 'ready',
}));
jest.mock('~/components/Linsight/Execution/taskTurnLoad', () => ({
  TaskTurnLoadContext: jest.requireActual('react').createContext(null),
}));
jest.mock('~/components/Linsight/Execution/stepUtils', () => ({}));
jest.mock('~/components/Linsight/Execution/PinnedTaskPanel', () => ({ PinnedTaskPanel: () => null }));
jest.mock('~/components/Linsight/Artifacts/WorkspacePanel', () => ({ WorkspacePanel: () => null }));
jest.mock('~/api/linsight', () => ({}));
jest.mock('~/api/messageExport', () => ({}));
jest.mock('~/api/request', () => ({ showApiError: () => undefined }));
jest.mock('~/types/chat', () => ({ QueryKeys: {} }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockNoop }) }));
jest.mock('~/common', () => ({ NotificationSeverity: { WARNING: 'warning' } }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('./Landing', () => ({ __esModule: true, default: () => { mockLanding(); return <div>Welcome</div>; } }));
jest.mock('./DailyFeaturedApps', () => ({ DailyFeaturedApps: () => <div>Featured apps</div> }));
jest.mock('./Presentation', () => ({ __esModule: true, default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
jest.mock('~/components/Chat/AiChatInput', () => ({
  __esModule: true,
  default: ({ elevated, value, onChange, onSend }: { elevated?: boolean; value: string; onChange: (value: string) => void; onSend: (text: string) => void }) => <>
    <input aria-label={elevated ? 'Landing composer' : 'Conversation composer'} value={value} onChange={event => onChange(event.target.value)} />
    <button onClick={() => onSend(value)}>Send</button>
  </>,
}));
jest.mock('~/components/Chat/AiChatMessages', () => ({
  __esModule: true,
  default: ({ messages }: { messages: { text: string }[] }) => <div>{messages.map(message => message.text).join('\n')}</div>,
}));
jest.mock('~/components/Chat/MessageSelection', () => ({ ExportFormatSheet: () => null, MessageSelectionToolbar: () => null }));
jest.mock('~/pages/Subscription/Article/AddToKnowledgeModal', () => ({ AddToKnowledgeModal: () => null }));

function View({ revision = 0 }: { revision?: number }) {
  return <MemoryRouter initialEntries={['/c/new']}><Routes><Route path="/c/:conversationId" element={<ChatView index={revision} />} /></Routes></MemoryRouter>;
}
function open() {
  return render(<View />);
}
beforeEach(() => {
  localStorage.clear();
  mockConfigReady = false;
  mockStreaming = false;
});

test('ordinary new chats still show the welcome page', () => {
  open();
  expect(screen.getByText('Welcome')).toBeInTheDocument();
  expect(screen.getByText('Featured apps')).toBeInTheDocument();
  expect(screen.getByRole('textbox', { name: 'Landing composer' })).toBeInTheDocument();
});

test('a mobile space ask never mounts the welcome page while config and send become ready', async () => {
  let accept: (accepted: boolean) => void = () => undefined;
  mockSend.mockImplementation(() => new Promise(resolve => { accept = resolve; }));
  parkChatAsk({ text: 'Question from space', modelId: 1, space: { id: '11', name: 'Space' } });
  const view = open();
  expect(mockLanding).not.toHaveBeenCalled();
  expect(screen.getByRole('textbox', { name: 'Conversation composer' })).toBeInTheDocument();
  expect(mockSend).not.toHaveBeenCalled();
  mockConfigReady = true;
  view.rerender(<View revision={1} />);
  expect(mockSend).toHaveBeenCalledTimes(1);
  expect(mockLanding).not.toHaveBeenCalled();
  expect(screen.queryByText('Featured apps')).not.toBeInTheDocument();
  await act(async () => { accept(true); });
  expect(screen.getByText('Question from space')).toBeInTheDocument();
  expect(mockLanding).not.toHaveBeenCalled();
});

test('an unavailable model returns to the editable welcome composer', () => {
  mockConfigReady = true;
  parkChatAsk({ text: 'Keep my question', modelId: 99, space: { id: '11', name: 'Space' } });
  open();
  expect(screen.getByRole('textbox', { name: 'Landing composer' })).toHaveValue('Keep my question');
  expect(mockSend).not.toHaveBeenCalled();
});


function PersistentView({ onNavigate }: { onNavigate: (navigate: ReturnType<typeof useNavigate>) => void }) {
  onNavigate(useNavigate());
  // Like the KeepAlive shell, keep the chat mounted while location is settings.
  return <ChatView id="new" />;
}

test('a cached unsent project draft survives settings and resets on an explicit new intent', () => {
  let navigate: ReturnType<typeof useNavigate> = () => undefined;
  const projectPath = '/c/new?projectId=11111111-1111-4111-8111-111111111111';
  render(<MemoryRouter initialEntries={[{ pathname: '/c/new', search: projectPath.slice('/c/new'.length), state: { newChatKey: 'draft-a' } }]}>
    <PersistentView onNavigate={value => { navigate = value; }} />
  </MemoryRouter>);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Unsent project question' } });
  act(() => navigate('/settings/account?dshSettings=1'));
  expect(screen.getByRole('textbox')).toHaveValue('Unsent project question');
  act(() => navigate(projectPath, { state: { newChatKey: 'draft-a' } }));
  expect(screen.getByRole('textbox')).toHaveValue('Unsent project question');
  act(() => navigate(projectPath, { state: { newChatKey: 'draft-b' } }));
  expect(screen.getByRole('textbox')).toHaveValue('');
});

test('an old pending send does not clear the next project draft text', async () => {
  let finish: (accepted: boolean) => void = () => undefined;
  mockSend.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  mockConfigReady = true;
  let navigate: ReturnType<typeof useNavigate> = () => undefined;
  render(<MemoryRouter initialEntries={[{ pathname: '/c/new', state: { newChatKey: 'draft-a' } }]}>
    <PersistentView onNavigate={value => { navigate = value; }} />
  </MemoryRouter>);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Question A' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  expect(mockSend).toHaveBeenCalledWith('Question A');
  act(() => navigate('/c/new', { state: { newChatKey: 'draft-b' } }));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Question B' } });
  await act(async () => { finish(true); });
  expect(screen.getByRole('textbox')).toHaveValue('Question B');
});
