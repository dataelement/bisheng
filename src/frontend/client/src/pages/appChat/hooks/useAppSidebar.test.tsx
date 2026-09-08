import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
// Test harness for the EXISTING recoil-backed sidebar hook; ledger #5 bans new
// atoms/selectors, not the provider needed to render the store under test.
// eslint-disable-next-line no-restricted-imports
import { RecoilRoot } from 'recoil';
import { getAppConversationsApi, getAssistantDetailApi, getFlowApi } from '~/api/apps';
import { useAppSidebar } from './useAppSidebar';

jest.mock('~/api/apps', () => ({
  getAppConversationsApi: jest.fn(),
  getAssistantDetailApi: jest.fn(),
  getFlowApi: jest.fn(),
}));

jest.mock('~/Providers', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

// `~/utils` and `~/hooks` are barrels that reach ESM-only packages jest does not
// transform. Stub only what this hook uses.
jest.mock('~/utils', () => ({
  copyText: jest.fn(),
  generateUUID: () => 'generated-id',
  displayConversationTitle: (title?: string, fallback?: string) => title || fallback || '',
}));

jest.mock('~/hooks', () => ({
  // Mirrors the real useLocalize: a FRESH closure on every call. Handing back a
  // stable function here would make this test pass against the buggy code too.
  useLocalize: () => (key: string) => key,
}));

const mockGetAppConversations = getAppConversationsApi as jest.Mock;
const mockGetAssistantDetail = getAssistantDetailApi as jest.Mock;
const mockGetFlow = getFlowApi as jest.Mock;

/** Mount the hook under the /app/:conversationId/:fid/:type route it really runs on. */
function wrapper({ children }: { children: ReactNode }) {
  return (
    <RecoilRoot>
      <MemoryRouter initialEntries={['/app/chat-new/flow-1/10']}>
        <Routes>
          <Route path="/app/:conversationId/:fid/:type" element={<>{children}</>} />
        </Routes>
      </MemoryRouter>
    </RecoilRoot>
  );
}

describe('useAppSidebar conversation fetching', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetFlow.mockResolvedValue({ status_code: 200, data: { id: 'flow-1', name: 'App' } });
    mockGetAssistantDetail.mockResolvedValue({ status_code: 200, data: { id: 'flow-1', name: 'App' } });
  });

  /**
   * Regression guard for the request storm on /api/v1/workstation/app/conversations.
   *
   * The fetch writes the result into Recoil, which re-renders the hook. If the
   * auto-fetch effect depends on anything that is rebuilt every render — and
   * `useLocalize()` returns a fresh closure every render — each response
   * schedules the next request and the endpoint is hammered forever.
   */
  it('fetches the conversation list once, even though the fetch re-renders the hook', async () => {
    mockGetAppConversations.mockResolvedValue({
      data: { list: [{ chat_id: 'chat-1', name: 'Existing', flow_id: 'flow-1', flow_type: 10 }] },
    });

    const { result } = renderHook(() => useAppSidebar(), { wrapper });

    await waitFor(() => expect(result.current.conversations.length).toBeGreaterThan(0));
    // Give any self-sustaining effect several chances to fire again.
    await new Promise((resolve) => setTimeout(resolve, 150));

    expect(mockGetAppConversations).toHaveBeenCalledTimes(1);
  });

  it('does not re-fetch when the list comes back empty either', async () => {
    mockGetAppConversations.mockResolvedValue({ data: { list: [] } });

    renderHook(() => useAppSidebar(), { wrapper });

    await waitFor(() => expect(mockGetAppConversations).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 150));

    expect(mockGetAppConversations).toHaveBeenCalledTimes(1);
  });
});
