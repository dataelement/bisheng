import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { DepartmentMember } from '@/types/api/department';
import type { useMemberTableController } from './MemberTable';
import { MemberTableView } from './MemberTableView';

vi.mock('@/pages/LoginPage/UserPwdModal', () => ({ default: () => null }));
vi.mock('./CreateLocalMemberDialog', () => ({ CreateLocalMemberDialog: () => null }));
vi.mock('./OrganizationMemberEditDialog', () => ({ OrganizationMemberEditDialog: () => null }));
afterEach(cleanup);

function setup(identity: 'is_child_admin' | 'is_department_admin', changes: Partial<DepartmentMember> = {}) {
    const member: DepartmentMember = {
        user_id: 82, user_name: 'Self', external_id: 'self-admin', department_id: 31,
        is_primary: 1, source: 'local', create_time: '2026-11-25', enabled: true,
        roles: [], user_groups: [], ...changes,
    };
    const handleEditUser = vi.fn();
    const controller = {
        deptId: 'experience', departmentId: 31, deptName: 'Experience', isPrimaryFilter: 'all',
        isArchived: false, directOnly: true, t: (key: string) => key,
        directAdmins: [], inheritedAdmins: [], members: [member], memberDisplayNames: new Map(),
        page: 1, total: 1, directTotal: 1, user: { user_id: 82, role: 'user', [identity]: true },
        fmtTime: (value: string) => value, handleEditUser,
        mrc: { totalWidth: 800, getThProps: () => ({}), getTdProps: () => ({}), startResize: vi.fn() },
    } as unknown as ReturnType<typeof useMemberTableController>;
    render(<MemberTableView controller={controller} />);
    return { member, handleEditUser };
}

it.each(['is_child_admin', 'is_department_admin'] as const)('opens own member editor from row and menu for %s', async (identity) => {
    const { member, handleEditUser } = setup(identity);
    const user = userEvent.setup();
    await user.click(screen.getByText('Self'));
    expect(handleEditUser).toHaveBeenLastCalledWith(member);
    handleEditUser.mockClear();
    await user.click(screen.getByRole('button', { name: 'more Self' }));
    const edit = await screen.findByRole('menuitem', { name: 'edit' });
    expect(edit).not.toHaveAttribute('aria-disabled', 'true');
    await user.click(edit);
    expect(handleEditUser).toHaveBeenCalledExactlyOnceWith(member);
});

it.each([
    { enabled: false },
    { department: { dept_id: 'experience', name: 'Experience', status: 'archived' } },
    { roles: [{ id: 1, role_name: 'System administrator' }] },
])('keeps protected own member rows read-only: %j', async (changes) => {
    const { handleEditUser } = setup('is_child_admin', changes);
    const user = userEvent.setup();
    await user.click(screen.getByText('Self'));
    expect(handleEditUser).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'more Self' }));
    expect(await screen.findByRole('menuitem', { name: 'edit' })).toHaveAttribute('aria-disabled', 'true');
});
