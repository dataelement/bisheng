import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createContext } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { DepartmentMember } from '@/types/api/department';
import { MemberTable } from './MemberTable';

const mocks = vi.hoisted(() => ({ members: vi.fn(), copy: vi.fn(), reset: vi.fn() }));
vi.mock('@/controllers/API/department', () => ({
    getDepartmentMembersApi: mocks.members,
    getDepartmentAdminsApi: vi.fn(async () => []),
    getDepartmentPathTreeApi: vi.fn(async () => ({ roots: [] })),
}));
vi.mock('@/controllers/API/user', () => ({ disableUserApi: vi.fn(async () => undefined) }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@/utils', async importOriginal => ({ ...(await importOriginal<object>()), copyText: mocks.copy }));
vi.mock('@/contexts/userContext', () => ({ userContext: createContext({ user: { role: 'admin', user_id: 1 } }) }));
vi.mock('@/pages/LoginPage/UserPwdModal', async () => {
    const { forwardRef, useImperativeHandle } = await import('react');
    return { default: forwardRef((_props, ref) => { useImperativeHandle(ref, () => ({ open: mocks.reset })); return null; }) };
});
vi.mock('./CreateLocalMemberDialog', () => ({ CreateLocalMemberDialog: () => null }));
vi.mock('./OrganizationMemberEditDialog', () => ({
    OrganizationMemberEditDialog: ({ open, member }: { open: boolean; member: DepartmentMember | null }) =>
        open ? <div data-testid="identity-editor">{member?.user_id}</div> : null,
}));

const rawAccount = `000Case${'X'.repeat(64)}\n`;
const member: DepartmentMember = {
    user_id: 7, user_name: 'Nickname7', external_id: rawAccount, person_id: rawAccount,
    department_id: 1, is_primary: 1, source: 'local', create_time: '2026-11-10', enabled: true, user_groups: [], roles: [],
};
const props = {
    deptId: 'dept-1', deptName: 'Department', onChanged: vi.fn(), isPrimaryFilter: 'all', onFilterChange: vi.fn(),
    dept: { id: 1, dept_id: 'dept-1', name: 'Department', parent_id: null, path: '/1/', sort_order: 0,
        source: 'local', status: 'active', is_tenant_root: false, mounted_tenant_id: null, children: [] },
};
beforeEach(() => {
    vi.clearAllMocks(); mocks.copy.mockResolvedValue(undefined);
    mocks.members.mockResolvedValue({ data: [member], total: 1 });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const open = async () => {
    const rendered = render(<MemberTable {...props} />);
    await screen.findByText(member.user_name);
    return rendered.container.querySelector('[data-member-row="7"]') as HTMLElement;
};

it('shows independent nickname/account columns and copies the entire original historical account', async () => {
    const row = await open();
    expect(screen.getByRole('columnheader', { name: /^accountIdentity\.nickname/ })).toBeVisible();
    expect(screen.getByRole('columnheader', { name: /^accountIdentity\.account/ })).toBeVisible();
    expect(within(row).getByText(rawAccount.trim())).toHaveAttribute('title', rawAccount);
    fireEvent.click(within(row).getByRole('button', { name: 'accountIdentity.copyAccount' }));
    await waitFor(() => expect(mocks.copy).toHaveBeenCalledWith(rawAccount));
    expect(screen.queryByTestId('identity-editor')).not.toBeInTheDocument();
    fireEvent.click(within(row).getByText(member.user_name));
    expect(screen.getByTestId('identity-editor')).toHaveTextContent('7');
});

it.each([null, 'LegacyInternalId'])('shows an explicitly missing account without substituting another identity (%s)', async legacyAlias => {
    mocks.members.mockResolvedValueOnce({ data: [{ ...member, external_id: null, person_id: legacyAlias }], total: 1 });
    const row = await open();
    expect(within(row).getByText('accountIdentity.noAccount')).toBeVisible();
    expect(within(row).queryByRole('button', { name: 'accountIdentity.copyAccount' })).not.toBeInTheDocument();
    expect(within(row).getAllByText(member.user_name)).toHaveLength(1);
});

it('keeps switch, password reset, and selected text from opening the row editor', async () => {
    const row = await open();
    fireEvent.click(within(row).getByRole('switch'));
    expect(screen.queryByTestId('identity-editor')).not.toBeInTheDocument();
    fireEvent.click(within(row).getByRole('button', { name: 'system.resetPwd' }));
    expect(mocks.reset).toHaveBeenCalledWith(7);
    expect(screen.queryByTestId('identity-editor')).not.toBeInTheDocument();
    vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => rawAccount } as Selection);
    fireEvent.click(within(row).getByText(member.user_name));
    expect(screen.queryByTestId('identity-editor')).not.toBeInTheDocument();
});

it('does not open disabled accounts from a member row', async () => {
    mocks.members.mockResolvedValueOnce({ data: [{ ...member, enabled: false }], total: 1 });
    const row = await open(); fireEvent.click(within(row).getByText(member.user_name));
    expect(screen.queryByTestId('identity-editor')).not.toBeInTheDocument();
});

it('searches the current department by nickname or raw account and clears back to the first page', async () => {
    await open();
    const search = screen.getByRole('searchbox', { name: 'accountIdentity.search' });
    fireEvent.change(search, { target: { value: '000Case' } });
    fireEvent.keyDown(search, { key: 'Enter' });
    await waitFor(() => expect(mocks.members).toHaveBeenLastCalledWith('dept-1', expect.objectContaining({ page: 1, keyword: '000Case' })));
    fireEvent.click(screen.getByRole('button', { name: 'sharedUi.clear' }));
    await waitFor(() => expect(mocks.members).toHaveBeenLastCalledWith('dept-1', { page: 1, limit: 20, is_primary: undefined }));
});
