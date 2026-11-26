import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CreateUser } from './CreateUser';

const mocks = vi.hoisted(() => ({ create: vi.fn(), encrypt: vi.fn(), copy: vi.fn(), error: vi.fn() }));
vi.mock('@/controllers/API/user', () => ({ createUserApi: mocks.create }));
vi.mock('@/pages/LoginPage/utils', () => ({ handleEncrypt: mocks.encrypt }));
vi.mock('@/utils', async importOriginal => ({ ...(await importOriginal<object>()), copyText: mocks.copy }));
vi.mock('@/controllers/request', () => ({ handleUiRequest: (callback: () => Promise<void>) => () => callback().catch(mocks.error) }));
vi.mock('./UserRoleItem', () => ({
    default: ({ onChange }: { onChange: (groups: string[], roles: string[]) => void }) =>
        <button type="button" onClick={() => onChange(['9'], ['2'])}>SelectRoles</button>,
}));
beforeEach(() => { vi.clearAllMocks(); mocks.encrypt.mockResolvedValue('encrypted'); mocks.copy.mockResolvedValue(undefined); });
afterEach(cleanup);

it('keeps the legacy entry on the same separate account/nickname contract and locks role editing during save', async () => {
    let finish!: () => void;
    mocks.create.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve; }));
    const onSave = vi.fn(); const onClose = vi.fn();
    render(<CreateUser open onClose={onClose} onSave={onSave} />);
    const account = screen.getByLabelText('accountIdentity.account');
    const nickname = screen.getByLabelText('accountIdentity.nickname');
    fireEvent.change(account, { target: { value: ' 000Case\t01 ' } });
    fireEvent.change(nickname, { target: { value: 'Nick name' } });
    fireEvent.change(screen.getByLabelText('system.initialPassword'), { target: { value: 'Abcd12_!' } });
    fireEvent.click(screen.getByRole('button', { name: 'SelectRoles' }));
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith('Nickname', 'encrypted', [{ group_id: 9, role_ids: [2] }], '000Case01'));
    expect(account).toBeDisabled(); expect(screen.getByRole('button', { name: 'SelectRoles' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'cancel' })).toBeDisabled();
    await act(async () => finish());
    expect(onSave).toHaveBeenCalledTimes(1); expect(onClose).toHaveBeenCalledWith(false);
});

it('rejects a 33-code-point nickname at the legacy creation entry', () => {
    render(<CreateUser open onClose={vi.fn()} onSave={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('accountIdentity.nickname'), { target: { value: '𠮷'.repeat(33) } });
    expect(screen.getByLabelText('accountIdentity.nickname')).toHaveAttribute('aria-invalid', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }));
    expect(mocks.create).not.toHaveBeenCalled();
});
