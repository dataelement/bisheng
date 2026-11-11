import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
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
jest.mock('~/api/user', () => ({ uploadUserAvatarFileApi: jest.fn() }));
jest.mock('./PasswordForm', () => ({ PasswordForm: () => null }));
jest.mock('./NicknameEditor', () => ({
    NicknameEditor: ({ onSaved }: { onSaved: (value: { user_id: number; user_name: string; external_id: string }) => void }) =>
        <button onClick={() => onSaved({ user_id: 7, user_name: 'NewNickname', external_id: 'Case01' })}>save-fixture-nickname</button>,
}));

it('shows the raw read-only account and copies its full original value', async () => {
    const client = new QueryClient();
    const account = ` Legacy\n${'A'.repeat(80)} `;
    render(<QueryClientProvider client={client}><AccountSection username="Nickname" avatarUrl="" account={account} /></QueryClientProvider>);
    expect(screen.getByLabelText('accountIdentity.account')).toHaveAttribute('readonly');
    fireEvent.click(screen.getByRole('button', { name: 'accountIdentity.copyAccount' }));
    await waitFor(() => expect(copyText).toHaveBeenCalledWith(account));
    client.clear();
});

it('uses no nickname fallback for a missing account', () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><AccountSection username="Nickname" avatarUrl="" account={null} /></QueryClientProvider>);
    expect(screen.getByLabelText('accountIdentity.account')).toHaveValue('');
    expect(screen.getByPlaceholderText('accountIdentity.noAccount')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'accountIdentity.copyAccount' })).toBeDisabled();
    client.clear();
});

it('updates the existing user and query caches after a successful rename', async () => {
    const client = new QueryClient();
    const original = { id: '7', username: 'OldNickname', name: 'OldNickname', external_id: 'Case01', role: 'user', avatar: '' } as TUser;
    client.setQueryData([QueryKeys.user], original);
    render(<QueryClientProvider client={client}><AccountSection username="OldNickname" avatarUrl="" account="Case01" /></QueryClientProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'accountIdentity.editNickname' }));
    fireEvent.click(screen.getByRole('button', { name: 'save-fixture-nickname' }));
    expect(screen.getByText('NewNickname')).toBeInTheDocument();
    expect(client.getQueryData<TUser>([QueryKeys.user])).toMatchObject({ id: '7', username: 'NewNickname', name: 'NewNickname', role: 'user', external_id: 'Case01' });
    expect(mockSetUser).toHaveBeenCalledWith(expect.any(Function));
    const update = mockSetUser.mock.calls[0][0] as (value: TUser) => TUser;
    expect(update(original)).toMatchObject({ id: '7', username: 'NewNickname', role: 'user', external_id: 'Case01' });
    const another = { ...original, id: '8', username: 'AnotherIdentity' };
    expect(update(another)).toBe(another);
    client.clear();
});
