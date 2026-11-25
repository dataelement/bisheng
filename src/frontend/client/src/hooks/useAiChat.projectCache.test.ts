import { act, renderHook } from '@testing-library/react';
import type { SSESubmission } from './useAiChatSSE';
import useAiChat from './useAiChat';
import { dataService } from '~/types/chat';

const mockQueryClient = new (jest.requireActual('@tanstack/react-query').QueryClient)({
  defaultOptions: { queries: { retry: false, cacheTime: Infinity } },
});
let mockProjectAccount = { id: 'test-user', tenant_id: 1 };
const mockOpenedStreams: Array<{ submission: SSESubmission }> = [];
const mockAddConversation = jest.fn((data: unknown) => data);
const mockReportProjectCreated = jest.fn();
let mockDesktop = false;
jest.mock('~/utils/clientEnvironment', () => {
  const actual = jest.requireActual('~/utils/clientEnvironment');
  const snapshots = new Map();
  return { ...actual,
    getClientEnvironment: () => {
      const base = actual.getClientEnvironment();
      const channel = mockDesktop ? 'desktop' : 'web';
      if (snapshots.get(channel)?.base !== base) snapshots.set(channel, { base, value: { ...base, channel } });
      return snapshots.get(channel).value;
    },
    readDesktopPresentation: () => ({ reportProjectConversationCreated: mockReportProjectCreated }),
  };
});
jest.mock('react-activation', () => ({ useActivate: jest.fn() }));
jest.mock('recoil', () => ({ useRecoilState: (atom: { value?: unknown }) => [atom?.value, jest.fn()] }));
jest.mock('~/store', () => ({ __esModule: true, default: {
  chatModel: { value: { id: 1, name: 'test-model' } }, searchType: { value: '' }, selectedAgentTools: { value: [] },
} }));
jest.mock('~/store/linsight', () => ({
  SopStatus: { Running: 'running', Stoped: 'stoped', SopGenerating: 'sop_generating' },
  taskModeSkillsState: () => ({ value: [] }),
}));
jest.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: mockProjectAccount, isAuthenticated: true }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: { models: [{ id: 1, visual: true }] } }) }));
jest.mock('~/hooks/useKnowledgeSpaceAccess', () => ({
  useKnowledgeSpaceAccess: (selection: unknown[]) => ({ available: selection, blocked: false, message: '' }),
}));
jest.mock('~/utils/mediaAttachmentUtils', () => ({ isMediaAttachmentFile: () => false }));
jest.mock('~/hooks/useLinsightManager', () => ({
  useLinsightManager: () => ({ createLinsight: jest.fn(), updateLinsight: jest.fn(), linsightMap: new Map() }),
}));
jest.mock('~/api/linsight', () => ({ startLinsight: jest.fn().mockResolvedValue(undefined), getLinsightSessionVersionList: jest.fn().mockResolvedValue([]) }));
jest.mock('~/api/chatApi', () => ({ getAgentMessages: jest.fn().mockResolvedValue([]), getSessionName: jest.fn().mockResolvedValue('') }));
jest.mock('~/api/request', () => ({ __esModule: true, default: {} }));
jest.mock('~/types/chat', () => ({ QueryKeys: { allConversations: 'allConversations' }, dataService: { genTitle: jest.fn().mockResolvedValue({}) } }));
jest.mock('~/utils', () => ({ addConversation: (...args: [unknown]) => mockAddConversation(...args), updateConvoFields: (data: unknown) => data }));
jest.mock('@tanstack/react-query', () => ({ ...jest.requireActual('@tanstack/react-query'), useQueryClient: () => mockQueryClient }));
jest.mock('./useAiChatSSE', () => ({ openChatStream: (submission: SSESubmission) => {
  mockOpenedStreams.push({ submission });
  return { close: jest.fn() };
} }));

const latestStream = () => mockOpenedStreams[mockOpenedStreams.length - 1];
const renderChat = (conversationId: string) => renderHook(({ cid }) => useAiChat(cid), { initialProps: { cid: conversationId } });
beforeEach(() => {
  mockQueryClient.clear();
  mockProjectAccount = { id: 'test-user', tenant_id: 1 };
  mockOpenedStreams.length = 0;
  localStorage.clear();
  mockDesktop = false;
});

describe('project sidebar during creation', () => {
  const projectId = '11111111-1111-4111-8111-111111111111';
  const identity = `${window.location.origin}:1:test-user`;
  const snapshotKey = ['chat-projects', identity];
  const listKey = ['chat-projects-conversations', identity, projectId, ''];
  const seed = () => {
    window.history.replaceState({}, '', `/workspace/c/new?projectId=${projectId}`);
    mockQueryClient.setQueryData(snapshotKey, { identity: { tenant_id: 1, user_id: 1 },
      projects: [{ id: projectId, name: 'Project' }], memberships: [] });
    mockQueryClient.setQueryData(listKey, { pages: [{ data: [], total: 0, next_cursor: null }], pageParams: [undefined] });
    mockQueryClient.setQueryData(['allConversations'], { pages: [{ conversations: [] }], pageParams: [undefined] });
  };

  it.each([false, true])('publishes the created conversation before any answer finishes, desktop=%s', async desktop => {
    mockDesktop = desktop;
    seed();
    const { result, rerender } = renderChat('new');
    await act(async () => { await result.current.sendMessage('Project question'); });
    const turn = latestStream().submission;
    window.history.replaceState({}, '', '/workspace/c/other');
    rerender({ cid: 'other' });
    act(() => turn.onCreated('project-chat', { ...turn.userMessage, messageId: '42' }));
    expect(mockQueryClient.getQueryData(snapshotKey).memberships).toEqual([{ chat_id: 'project-chat', project_id: projectId }]);
    expect(mockQueryClient.getQueryData(listKey).pages[0].data).toEqual([expect.objectContaining({ conversationId: 'project-chat', title: 'com_ui_new_chat' })]);
    expect(mockQueryClient.getQueryData(['allConversations']).pages[0].conversations).toEqual([]);
    expect(mockAddConversation).not.toHaveBeenCalled();
    expect(mockReportProjectCreated.mock.calls).toEqual(desktop ? [[{ conversationId: 'project-chat', projectId }]] : []);
    act(() => turn.onEnd());
  });

  it('keeps the generated title in the project after the answer finishes', async () => {
    seed();
    jest.mocked(dataService.genTitle).mockResolvedValueOnce({ title: 'Project answer' });
    const { result } = renderChat('new');
    await act(async () => { await result.current.sendMessage('Project question'); });
    const turn = latestStream().submission;
    act(() => turn.onCreated('project-chat', { ...turn.userMessage, messageId: '42' }));
    await act(async () => { turn.onFinal({ conversation: { conversationId: 'project-chat' } }); turn.onEnd(); });
    expect(mockQueryClient.getQueryData(listKey).pages[0].data[0].title).toBe('Project answer');
  });

  it('publishes task-mode conversations at handoff without waiting for task completion', async () => {
    mockDesktop = true;
    seed();
    const { result } = renderChat('new');
    await act(async () => { await result.current.sendMessage('Project task', null, { taskMode: true }); });
    const turn = latestStream().submission;
    act(() => turn.onTaskHandoff?.({ session_version_id: 'sv-project', chat_id: 'project-task' }));
    expect(mockQueryClient.getQueryData(listKey).pages[0].data[0].conversationId).toBe('project-task');
    expect(mockQueryClient.getQueryData(snapshotKey).memberships).toEqual([{ chat_id: 'project-task', project_id: projectId }]);
    expect(mockReportProjectCreated).toHaveBeenCalledWith({ conversationId: 'project-task', projectId });
    act(() => turn.onEnd());
  });

  it('ignores late project writes after switching account', async () => {
    seed();
    const { result, rerender } = renderChat('new');
    await act(async () => { await result.current.sendMessage('Project question'); });
    const turn = latestStream().submission;
    mockProjectAccount = { id: 'other-user', tenant_id: 2 };
    rerender({ cid: 'new' });
    act(() => turn.onCreated('late-chat', { ...turn.userMessage, messageId: '42' }));
    expect(mockQueryClient.getQueryData(snapshotKey).memberships).toEqual([]);
    expect(mockQueryClient.getQueryData(listKey).pages[0].data).toEqual([]);
    act(() => turn.onEnd());
  });

  it('keeps ordinary creation in the ordinary list', async () => {
    window.history.replaceState({}, '', '/workspace/c/new');
    mockQueryClient.setQueryData(['allConversations'], { pages: [{ conversations: [] }], pageParams: [undefined] });
    const { result } = renderChat('new');
    await act(async () => { await result.current.sendMessage('Ordinary question'); });
    const turn = latestStream().submission;
    act(() => turn.onCreated('ordinary-chat', { ...turn.userMessage, messageId: '42' }));
    expect(mockAddConversation).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ conversationId: 'ordinary-chat' }));
    expect(mockQueryClient.getQueriesData({ queryKey: ['chat-projects-conversations'] })).toEqual([]);
    act(() => turn.onEnd());
  });
});
