import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useRolesController } from './Roles';

const api = vi.hoisted(() => ({ create: vi.fn(), list: vi.fn(), update: vi.fn() }));
vi.mock('@/controllers/API/user', () => ({
  createRoleV2Api: api.create,
  getRolesPageApi: api.list,
  updateRoleV2Api: api.update,
  deleteRoleV2Api: vi.fn(),
  getRoleMenuV2Api: vi.fn().mockResolvedValue([]),
}));
vi.mock('@/controllers/API/department', () => ({ getDepartmentChildrenApi: vi.fn().mockResolvedValue([]) }));
vi.mock('@/contexts/userContext', async () => {
  const { createContext } = await import('react');
  return { userContext: createContext({ user: { role: 'admin' } }) };
});
vi.mock('@/components/bs-ui/table/useResizableColumns', () => ({ useResizableColumns: () => ({}) }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@bisheng/ui', () => ({ Switch: () => null, toast: { show: vi.fn() } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue({ data: [], total: 0 });
  api.create.mockResolvedValue({ id: 24 });
});

it.each(['tenant', 'global'] as const)('submits an explicit %s type while keeping edits separate', async kind => {
  const { result } = renderHook(() => useRolesController());
  await act(async () => { result.current.openCreate(); });
  expect(result.current.roleType).toBe('tenant');
  await act(async () => {
    result.current.setRoleName(' New role ');
    if (kind === 'global') result.current.setRoleType('global');
  });
  await act(async () => { await result.current.submitRole(); });
  expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ role_name: 'New role', role_type: kind }));
  expect(api.update).not.toHaveBeenCalled();
});
