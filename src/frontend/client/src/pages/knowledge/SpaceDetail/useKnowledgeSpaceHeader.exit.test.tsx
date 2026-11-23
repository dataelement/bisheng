import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useKnowledgeSpaceHeader } from './useKnowledgeSpaceHeader';
import type { UseKnowledgeSpaceHeaderOptions } from './knowledgeSpaceTypes';

const mockExitStatus = jest.fn();
const mockEnsure = jest.fn();
jest.mock('~/hooks', () => ({ useAuthContext: () => ({ user: { id: '7' } }), useVersionManagementEnabled: () => false }));
jest.mock('~/components/CopyShareLinkButton', () => ({ buildClientShareUrl: (path: string) => path }));
jest.mock('../hooks/useKnowledgeSpacePermissions', () => ({
  useKnowledgeSpaceActions: () => ({ actions: {}, ensureSpaceActions: mockEnsure }),
  hasKnowledgeSpaceAction: () => true,
}));
jest.mock('~/api/knowledgeSpaceExit', () => ({ resolveSpaceExitScope: async () => '42', getSpaceExitStatus: (...args: unknown[]) => mockExitStatus(...args) }));
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}
it.each([
  [true, null, true],
  [false, 'organization_grant', false],
  [false, 'creator', false],
  [false, 'no_personal_grant', false],
])('uses authoritative detail eligibility %s/%s', async (can_exit, reason, expected) => {
  mockExitStatus.mockResolvedValue({ can_exit, reason });
  const options = { space: { id: '3', role: 'admin', spaceKind: 'normal' }, selectedFiles: new Set(), onDeleteFile: jest.fn(), localize: (key: string) => key, showToast: jest.fn() } as unknown as UseKnowledgeSpaceHeaderOptions;
  const { result } = renderHook(() => useKnowledgeSpaceHeader(options), { wrapper });
  expect(result.current.canLeaveSpace).toBe(false);
  await waitFor(() => expect(mockExitStatus).toHaveBeenCalled());
  await waitFor(() => expect(result.current.canLeaveSpace).toBe(expected));
  expect(result.current.canDeleteSpace).toBe(false);
});
