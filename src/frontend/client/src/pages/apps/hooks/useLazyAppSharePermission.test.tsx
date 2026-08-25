import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { checkResourceAction } from '~/api/permission';
import {
  getAppPermissionResourceType,
  useLazyAppSharePermission,
} from './useLazyAppSharePermission';

jest.mock('~/api/permission', () => ({
  checkResourceAction: jest.fn(),
}));

const mockCheckResourceAction = checkResourceAction as jest.Mock;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function QueryWrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe('useLazyAppSharePermission', () => {
  beforeEach(() => jest.clearAllMocks());

  it('maps supported app flow types to permission resource types', () => {
    expect(getAppPermissionResourceType(10)).toBe('workflow');
    expect(getAppPermissionResourceType(5)).toBe('assistant');
    expect(getAppPermissionResourceType(1)).toBeNull();
  });

  it('loads share permission on demand and reuses the fresh result', async () => {
    mockCheckResourceAction.mockResolvedValue({ allowed: true });
    const { result } = renderHook(
      () => useLazyAppSharePermission({ id: 'flow-1', flow_type: 10 }),
      { wrapper: createWrapper() },
    );

    expect(result.current.canShare).toBe(false);
    expect(mockCheckResourceAction).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.ensureSharePermission();
    });
    await waitFor(() => expect(result.current.canShare).toBe(true));

    await act(async () => {
      await result.current.ensureSharePermission();
    });
    expect(mockCheckResourceAction).toHaveBeenCalledTimes(1);
    expect(mockCheckResourceAction).toHaveBeenCalledWith({
      resource_type: 'workflow',
      resource_id: 'flow-1',
      action: 'share',
    });
  });

  it('trusts an eager false result without issuing a lazy request', async () => {
    const { result } = renderHook(
      () => useLazyAppSharePermission({ id: 'assistant-1', flow_type: 5, can_share: false }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      await result.current.ensureSharePermission();
    });

    expect(result.current.canShare).toBe(false);
    expect(mockCheckResourceAction).not.toHaveBeenCalled();
  });
});
