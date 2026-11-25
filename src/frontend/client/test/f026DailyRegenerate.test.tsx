import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useAiChat from '~/hooks/useAiChat';
import type { SSESubmission } from '~/hooks/useAiChatSSE';
import type { SelectedOrgKb } from '~/store/modeltype';

const mocks = vi.hoisted(() => ({ get: vi.fn(), confirm: vi.fn(), streams: [] as SSESubmission[], selection: [] as SelectedOrgKb[], blocked: false }));
vi.mock('~/api/request', () => ({ default: { get: mocks.get } }));
vi.mock('~/api/citationScope', () => ({ getCitationAccessScope: () => [] }));
vi.mock('~/api/hydrateStreamChatCitations', () => ({ hydrateStreamChatCitations: vi.fn() }));
vi.mock('~/hooks/useAiChatSSE', () => ({ openChatStream: (s: SSESubmission) => { mocks.streams.push(s); return { close: vi.fn() }; } }));
vi.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
vi.mock('~/Providers', () => ({ useConfirm: () => mocks.confirm, useToastContext: () => ({ showToast: vi.fn() }) }));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ setQueryData: vi.fn() }) }));
vi.mock('recoil', () => ({ useRecoilState: (value: unknown) => [value, vi.fn()] }));
vi.mock('~/store', () => ({ default: { chatModel: { id: 1, name: 'Model' }, selectedAgentTools: [], searchType: '' } }));
vi.mock('~/store/linsight', () => ({ SopStatus: {}, taskModeSkillsState: () => [] }));
vi.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
vi.mock('~/hooks/useConversationKnowledge', () => ({ useConversationKnowledge: () => ({ selectedOrgKbs: mocks.selection, setSelectedOrgKbs: vi.fn(), promoteSelection: vi.fn() }) }));
vi.mock('~/hooks/useKnowledgeSpaceAccess', () => ({ useKnowledgeSpaceAccess: () => ({ available: mocks.selection, blocked: mocks.blocked }) }));
vi.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: { id: 'owner' } }) }));
vi.mock('~/components/Chat/desktopConversationBridge', () => ({ useDesktopConversationActivity: vi.fn(), useDesktopConversationRenamed: vi.fn() }));
vi.mock('~/utils', () => ({ addConversation: vi.fn(), updateConvoFields: vi.fn() }));
vi.mock('~/types/chat', () => ({ QueryKeys: {}, dataService: {} }));
vi.mock('~/hooks/useLinsightManager', () => ({ useLinsightManager: () => ({ linsightMap: new Map() }) }));
vi.mock('~/api/linsight', () => ({ getLinsightSessionVersionList: vi.fn(), startLinsight: vi.fn() }));
vi.mock('~/hooks/inviteQuotaRefresh', () => ({ refreshInviteQuota: vi.fn() }));

function history(recorded?: unknown) {
  mocks.get.mockImplementation(async (url: string) => url.endsWith('/agent') ? { data: [
    { message_id: 21, chat_id: 'daily', category: 'question', is_bot: false, message: { query: 'Original question' }, knowledge_scope_recorded: recorded },
    { message_id: 22, chat_id: 'daily', category: 'agent_answer', is_bot: true, message: { msg: 'Original answer' } },
  ] } : { data: { name: 'Daily' } });
}
async function open() {
  const chat = renderHook(({ cid }) => useAiChat(cid), { initialProps: { cid: 'daily' } });
  await waitFor(() => expect(chat.result.current.messages).toHaveLength(2));
  return chat;
}
afterEach(cleanup);
beforeEach(() => {
  mocks.confirm.mockReset(); mocks.blocked = false; mocks.streams.length = 0;
  mocks.selection = [{ id: '99', type: 'space', name: 'Current space', tag: { id: 14, name: 'Current tag' } }];
  history(true);
});

describe('daily completion material scope', () => {
  it('addresses the stored question, without serialising the changed picker or mutating the original turn', async () => {
    const { result } = await open();
    await act(async () => { await result.current.regenerate(result.current.messages[1].parentMessageId); });
    expect(mocks.confirm).not.toHaveBeenCalled();
    expect(mocks.streams[0].payload).toMatchObject({ isRegenerate: true, messageId: '21', conversationId: 'daily', useCurrentMaterials: false });
    expect(mocks.streams[0].payload).not.toHaveProperty('use_knowledge_base');
    act(() => mocks.streams[0].onCreated('daily', { ...mocks.streams[0].userMessage, messageId: '23', knowledge_scope_recorded: true }));
    expect(result.current.messages.map(m => m.messageId)).toEqual(['21', '22', '23', expect.any(String)]);
    expect(result.current.messages[1].parentMessageId).toBe('21');
  });
  it.each([false, undefined, 'true'])('requests confirmation for unavailable or malformed history (%s); cancel sends nothing', async recorded => {
    history(recorded); mocks.confirm.mockResolvedValue(false);
    const { result } = await open();
    await act(async () => { await result.current.regenerate('21'); });
    expect(mocks.confirm).toHaveBeenCalledOnce();
    expect(mocks.streams).toHaveLength(0);
    expect(result.current.messages).toHaveLength(2);
  });
  it.each(['confirmed', 'explicit'])('only uses current space/tag on %s re-ask', async kind => {
    history(kind === 'explicit'); mocks.confirm.mockResolvedValue(true);
    const { result } = await open();
    await act(async () => { await result.current.regenerate('21', kind === 'explicit' ? 'current' : 'original'); });
    expect(mocks.streams).toHaveLength(1);
    expect(mocks.streams[0].payload).toMatchObject({ isRegenerate: true, useCurrentMaterials: true, messageId: '21', use_knowledge_base: { knowledge_space_ids: [99], knowledge_space_tag_filters: { '99': 14 } } });
  });
  it('records an intentionally empty filter on new questions instead of making them look like legacy turns', async () => {
    mocks.selection = [];
    const { result } = await open();
    await act(async () => { await result.current.sendMessage('New question'); });
    expect(JSON.parse(JSON.stringify(mocks.streams[0].payload)).use_knowledge_base.knowledge_space_tag_filters).toEqual({});
  });
  it.each([12048, 400])('does not substitute the picker on a server error (%i)', async code => {
    const { result } = await open();
    await act(async () => { await result.current.regenerate('21'); });
    act(() => { mocks.streams[0].onError('Rejected', code); mocks.streams[0].onEnd(); });
    expect(mocks.streams).toHaveLength(1);
    mocks.confirm.mockResolvedValue(false);
    await act(async () => { await result.current.regenerate('21'); });
    expect(mocks.confirm).toHaveBeenCalledTimes(code === 12048 ? 1 : 0);
    expect(mocks.streams).toHaveLength(code === 12048 ? 1 : 2);
  });
  it('requires fresh consent for an unsaved question and never sends its temporary ID as a retry target', async () => {
    const { result } = await open();
    await act(async () => { await result.current.sendMessage('Not persisted'); });
    act(() => { mocks.streams[0].onError('Offline'); mocks.streams[0].onEnd(); });
    const unsaved = result.current.messages[2].messageId;
    mocks.confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    await act(async () => { await result.current.regenerate(unsaved); });
    expect(mocks.streams).toHaveLength(1);
    await act(async () => { await result.current.regenerate(unsaved); });
    expect(mocks.streams).toHaveLength(2);
    expect(mocks.streams[1].payload.isRegenerate).toBeUndefined();
    expect(mocks.streams[1].payload.messageId).not.toBe(unsaved);
    expect(mocks.streams[1].payload.use_knowledge_base.knowledge_space_tag_filters).toEqual({ '99': 14 });
  });
  it('does not widen a re-ask with an unavailable live selection; original retries are independent of the picker', async () => {
    mocks.blocked = true;
    const { result } = await open();
    await act(async () => { await result.current.regenerate('21', 'current'); });
    expect(mocks.streams).toHaveLength(0);
    await act(async () => { await result.current.regenerate('21'); });
    expect(mocks.streams).toHaveLength(1);
    expect(mocks.streams[0].payload).not.toHaveProperty('use_knowledge_base');
  });
  it('does not turn a malformed saved picker tag into an unfiltered current-materials search', async () => {
    mocks.selection[0].tag = { name: 'Incomplete tag' } as SelectedOrgKb['tag'];
    const { result } = await open();
    await act(async () => { await result.current.regenerate('21', 'current'); });
    expect(mocks.streams).toHaveLength(0);
  });
  it('cancels outstanding consent after navigation', async () => {
    history(false);
    let resolve!: (answer: boolean) => void;
    mocks.confirm.mockImplementation(() => new Promise<boolean>(r => { resolve = r; }));
    const { result, rerender } = await open();
    let pending!: Promise<void>;
    act(() => { pending = result.current.regenerate('21'); });
    rerender({ cid: 'another' });
    await act(async () => { resolve(true); await pending; });
    expect(mocks.streams).toHaveLength(0);
  });
});
