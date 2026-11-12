import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ApiError } from '@bisheng/api-client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DepartmentMember } from '@/types/api/department';
import type { DepartmentMemberEditForm } from '@/controllers/API/department';
import { CreateLocalMemberDialog } from './CreateLocalMemberDialog';
import { OrganizationMemberEditDialog } from './OrganizationMemberEditDialog';

const mocks = vi.hoisted(() => ({
    create: vi.fn(), edit: vi.fn(), load: vi.fn(), encrypt: vi.fn(), copy: vi.fn(), error: vi.fn(), notify: vi.fn(),
    t: (key: string) => key,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('@/controllers/API/department', () => ({
    createDepartmentLocalMemberApi: mocks.create,
    applyDepartmentMemberEditApi: mocks.edit,
    getDepartmentMemberEditFormApi: mocks.load,
    getDepartmentAssignableRolesApi: vi.fn(async () => []),
    checkDepartmentMemberDeleteApi: vi.fn(), deleteDepartmentLocalMemberApi: vi.fn(),
}));
vi.mock('@/controllers/request', () => ({ showApiError: mocks.error, handleUiRequest: (callback: unknown) => callback }));
vi.mock('@/pages/LoginPage/utils', () => ({ handleEncrypt: mocks.encrypt }));
vi.mock('@/utils', async importOriginal => ({ ...(await importOriginal<object>()), copyText: mocks.copy }));
vi.mock('@/components/bs-comp/department/TreeDepartmentSelect', () => ({ TreeDepartmentSelect: () => null }));
vi.mock('@bisheng/ui', async importOriginal => ({
    ...(await importOriginal<typeof import('@bisheng/ui')>()), notification: { open: mocks.notify },
}));

const member: DepartmentMember = {
    user_id: 7, user_name: 'OldNickname', external_id: 'Case01', person_id: 'Case01', department_id: 1,
    is_primary: 1, source: 'local', create_time: '2026-11-10', enabled: true, user_groups: [], roles: [],
};
const editForm = (nickname = member.user_name, mode: DepartmentMemberEditForm['edit_mode'] = 'local_primary'): DepartmentMemberEditForm => ({
    edit_mode: mode, user: { user_id: member.user_id, user_name: nickname, person_id: member.person_id!, source: 'local' },
    context: { dept_id: 'dept-1', name: 'Department', is_primary: 1 }, primary_department: null,
    can_change_primary: false, affiliate_rows: [], assignable_roles_catalog: {}, context_role_ids: [],
    manageable_groups: [], current_group_ids: [], locked_group_ids: [],
});
const change = (field: HTMLElement, value: string) => fireEvent.change(field, { target: { value } });
const nickname = () => screen.getByRole('textbox', { name: 'accountIdentity.nickname' });
const account = () => screen.getByRole('textbox', { name: 'accountIdentity.account' });

beforeEach(() => {
    vi.clearAllMocks();
    mocks.encrypt.mockResolvedValue('encrypted');
    mocks.copy.mockResolvedValue(undefined);
    mocks.create.mockResolvedValue({ user_id: 7, user_name: 'Nickname', person_id: 'Case01' });
    mocks.edit.mockResolvedValue(undefined);
    mocks.load.mockResolvedValue(editForm());
});
afterEach(cleanup);

describe('create local member identity fields', () => {
    const open = () => {
        const callbacks = { onClose: vi.fn(), onCreated: vi.fn() };
        render(<CreateLocalMemberDialog deptId="dept-1" deptName="Department" {...callbacks} />);
        return callbacks;
    };
    const fill = () => {
        change(account(), 'Case01'); change(nickname(), 'Nickname');
        change(screen.getByLabelText('system.initialPassword'), 'Abcd12_!');
    };

    it('filters pasted whitespace, expands rules, and rejects invalid boundaries', async () => {
        open();
        change(account(), ' C\u00a0ase\t01 ');
        change(nickname(), ' Nick\u3000name\n ');
        expect(account()).toHaveValue('Case01'); expect(nickname()).toHaveValue('Nickname');
        fireEvent.click(screen.getByRole('button', { name: 'accountIdentity.accountRulesLabel' }));
        expect(document.getElementById('create-local-account-rules')).toHaveTextContent('accountIdentity.accountRules');
        change(account(), '_invalid');
        expect(account()).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByText('accountIdentity.errors.accountStart')).toBeVisible();
        change(account(), 'A'.repeat(65)); change(nickname(), '𠮷'.repeat(33));
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        expect(screen.getByText('accountIdentity.errors.accountLength')).toBeVisible();
        expect(screen.getByText('accountIdentity.errors.nicknameLength')).toBeVisible();
        expect(mocks.create).not.toHaveBeenCalled();
        await act(async () => Promise.resolve());
    });

    it('submits raw account case once, encrypts the password, and locks cancellation', async () => {
        let finish!: (value: { user_id: number; user_name: string; person_id: string }) => void;
        mocks.create.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
        const callbacks = open(); fill();
        const save = screen.getByRole('button', { name: 'save' });
        fireEvent.click(save); fireEvent.click(save);
        await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
        expect(mocks.create).toHaveBeenCalledWith('dept-1', { user_name: 'Nickname', person_id: 'Case01', password: 'encrypted', role_ids: [] });
        expect(account()).toBeDisabled(); expect(screen.getByRole('button', { name: 'cancel' })).toBeDisabled();
        await act(async () => finish({ user_id: 7, user_name: 'Nickname', person_id: 'Case01' }));
        expect(callbacks.onCreated).toHaveBeenCalledTimes(1); expect(callbacks.onClose).toHaveBeenCalledTimes(1);
    });

    it('keeps draft values and marks a server-side duplicate until the account changes', async () => {
        mocks.create.mockRejectedValueOnce(new ApiError({ status_code: 10613 }, { message: 'duplicate' }));
        const callbacks = open(); fill(); fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await screen.findByText('accountIdentity.errors.accountExists');
        expect(account()).toHaveValue('Case01'); expect(nickname()).toHaveValue('Nickname');
        expect(callbacks.onCreated).not.toHaveBeenCalled();
        change(nickname(), 'DifferentNickname'); expect(account()).toHaveAttribute('aria-invalid', 'true');
        change(account(), 'Case02'); expect(account()).toHaveAttribute('aria-invalid', 'false');
    });
});

describe('administrator nickname editor', () => {
    const open = async () => {
        const callbacks = { onClose: vi.fn(), onSaved: vi.fn() };
        const rendered = render(<OrganizationMemberEditDialog open deptId="dept-1" member={member} {...callbacks} />);
        await screen.findByLabelText('accountIdentity.nickname');
        return { ...callbacks, ...rendered };
    };

    it('keeps the original historical nickname and exact read-only account when saving other fields', async () => {
        const historical = ` historical name ${'x'.repeat(40)}`;
        mocks.load.mockResolvedValueOnce(editForm(historical));
        await open();
        expect(nickname()).toHaveValue(historical); expect(nickname()).toHaveAttribute('aria-invalid', 'false');
        expect(account()).toHaveValue('Case01'); expect(account()).toHaveAttribute('readonly');
        expect(screen.getByText('accountIdentity.nicknameEffectAdmin')).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(mocks.edit).toHaveBeenCalledWith('dept-1', 7, expect.objectContaining({ user_name: undefined })));
        expect(mocks.edit.mock.calls[0][2]).not.toHaveProperty('person_id');
    });

    it('blocks an overlong change, accepts 32 code points, and preserves the draft on failure', async () => {
        mocks.edit.mockRejectedValueOnce(new ApiError({ status_code: 10614 }, { message: 'nickname rejected' }));
        const callbacks = await open();
        change(nickname(), '𠮷'.repeat(33));
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        expect(mocks.edit).not.toHaveBeenCalled(); expect(nickname()).toHaveAttribute('aria-invalid', 'true');
        change(nickname(), '𠮷'.repeat(32));
        expect(screen.getByText('32/32')).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await screen.findByText('nickname rejected');
        expect(nickname()).toHaveValue('𠮷'.repeat(32)); expect(callbacks.onSaved).not.toHaveBeenCalled();
        change(nickname(), 'RetryName');
        expect(screen.queryByText('nickname rejected')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(callbacks.onSaved).toHaveBeenCalledTimes(1));
    });

    it.each(['affiliate', 'synced_primary'] as const)('keeps nickname read-only for %s members', async mode => {
        mocks.load.mockResolvedValueOnce(editForm(member.user_name, mode));
        await open(); expect(nickname()).toBeDisabled(); expect(account()).toHaveAttribute('readonly');
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(mocks.edit).toHaveBeenCalledTimes(1));
        expect(mocks.edit.mock.calls[0][2].user_name).toBeUndefined();
    });

    it('does not put a delayed response from the previously selected person into another editor', async () => {
        let finishOld!: (value: DepartmentMemberEditForm) => void;
        mocks.load.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; }));
        const second = { ...member, user_id: 8, user_name: 'NickEight', person_id: 'Case08' };
        const nextForm = editForm(second.user_name);
        nextForm.user = { ...nextForm.user, user_id: 8, person_id: 'Case08' };
        mocks.load.mockResolvedValueOnce(nextForm);
        const callbacks = { onClose: vi.fn(), onSaved: vi.fn() };
        const rendered = render(<OrganizationMemberEditDialog open deptId="dept-1" member={member} {...callbacks} />);
        rendered.rerender(<OrganizationMemberEditDialog open deptId="dept-1" member={second} {...callbacks} />);
        await waitFor(() => expect(nickname()).toHaveValue('NickEight'));
        await act(async () => finishOld(editForm('DelayedOldName')));
        expect(nickname()).toHaveValue('NickEight'); expect(account()).toHaveValue('Case08');
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(mocks.edit).toHaveBeenCalledWith('dept-1', 8, expect.objectContaining({ user_name: undefined })));
    });
});
