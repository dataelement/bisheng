import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { updateNicknameApi } from '~/api/user';
import type { TUser } from '~/types/chat';
import { QueryKeys } from '~/types/chat';
import { copyText } from '~/utils';
import { AccountSection } from './AccountSection';

const mockSetUser = jest.fn();
const mockToast = jest.fn();
jest.mock('recoil', () => ({ ...jest.requireActual('recoil'), useSetRecoilState: () => mockSetUser }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('~/utils', () => ({ copyText: jest.fn().mockResolvedValue(undefined) }));
jest.mock('~/api/user', () => ({ uploadUserAvatarFileApi: jest.fn(), updateNicknameApi: jest.fn() }));
jest.mock('./PasswordForm', () => ({ PasswordForm: () => null }));

it('shows the account as plain text and copies its full original value', async () => {
    const client = new QueryClient();
    const account = ` Legacy\n${'A'.repeat(80)} `;
    render(<QueryClientProvider client={client}><AccountSection username="Nickname" avatarUrl="" account={account} /></QueryClientProvider>);
    const accountValue = screen.getByText(account, { normalizer: value => value });
    const copyButton = screen.getByRole('button', { name: 'accountIdentity.copyAccount' });
    expect(accountValue).toBeVisible();
    expect(accountValue.closest('dd')).toContainElement(copyButton);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByText('accountIdentity.accountPurpose')).not.toBeInTheDocument();
    fireEvent.click(copyButton);
    await waitFor(() => expect(copyText).toHaveBeenCalledWith(account));
    client.clear();
});

it('uses no nickname fallback for a missing account', () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><AccountSection username="Nickname" avatarUrl="" account={null} /></QueryClientProvider>);
    expect(screen.getByText('accountIdentity.noAccount')).toBeVisible();
    expect(screen.getByRole('button', { name: 'accountIdentity.copyAccount' })).toBeDisabled();
    client.clear();
});

it('edits the nickname in place and updates the user and query caches', async () => {
    const client = new QueryClient();
    const original = { id: '7', username: 'OldNickname', name: 'OldNickname', external_id: 'Case01', role: 'user', avatar: '' } as TUser;
    jest.mocked(updateNicknameApi).mockResolvedValueOnce({ user_id: 7, user_name: 'NewNickname', external_id: 'Case01' });
    client.setQueryData([QueryKeys.user], original);
    render(<QueryClientProvider client={client}><AccountSection username="OldNickname" avatarUrl="" account="Case01" /></QueryClientProvider>);
    const nicknameField = screen.getByText('OldNickname').closest('dd');
    const editButton = screen.getByRole('button', { name: 'accountIdentity.editNickname' });
    expect(nicknameField).toContainElement(editButton);
    fireEvent.click(editButton);
    const input = screen.getByRole('textbox', { name: 'accountIdentity.nickname' });
    expect(nicknameField).toContainElement(input);
    expect(input).toHaveValue('OldNickname');
    expect(input).toHaveFocus();
    expect(screen.queryByText('OldNickname')).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'NewNickname' } });
    fireEvent.click(screen.getByRole('button', { name: 'com_ui_save' }));
    expect(await screen.findByText('NewNickname')).toBeInTheDocument();
    expect(client.getQueryData<TUser>([QueryKeys.user])).toMatchObject({ id: '7', username: 'NewNickname', name: 'NewNickname', role: 'user', external_id: 'Case01' });
    expect(mockSetUser).toHaveBeenCalledWith(expect.any(Function));
    const update = mockSetUser.mock.calls[0][0] as (value: TUser) => TUser;
    expect(update(original)).toMatchObject({ id: '7', username: 'NewNickname', role: 'user', external_id: 'Case01' });
    const another = { ...original, id: '8', username: 'AnotherIdentity' };
    expect(update(another)).toBe(another);
    client.clear();
});
