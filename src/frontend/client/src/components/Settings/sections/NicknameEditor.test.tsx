import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { updateNicknameApi, type NicknameProfile } from '~/api/user';
import { NicknameEditor } from './NicknameEditor';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/api/user', () => ({ updateNicknameApi: jest.fn() }));

const saved: NicknameProfile = { user_id: 7, user_name: 'New', external_id: 'Case01' };
const api = jest.mocked(updateNicknameApi);
const input = () => screen.getByLabelText('accountIdentity.nickname') as HTMLInputElement;
const save = () => screen.getByRole('button', { name: 'accountIdentity.saveNickname' });

function editor(nickname = 'Old') {
    const callbacks = { onCancel: jest.fn(), onSaved: jest.fn() };
    render(<NicknameEditor nickname={nickname} {...callbacks} />);
    return callbacks;
}

beforeEach(() => api.mockResolvedValue(saved));

it('filters whitespace, displays the rule and system-wide effect', () => {
    editor();
    fireEvent.change(input(), { target: { value: 'N ew\u3000\t' } });
    expect(input()).toHaveValue('New');
    expect(screen.getByText('3/32')).toBeInTheDocument();
    expect(screen.getByText('accountIdentity.nicknameRules')).toBeInTheDocument();
    expect(screen.getByText('accountIdentity.nicknameEffectSelf')).toBeInTheDocument();
});

it('counts code points and blocks a 33-character change', () => {
    editor();
    fireEvent.change(input(), { target: { value: '𠮷'.repeat(32) } });
    expect(screen.getByText('32/32')).toBeInTheDocument();
    expect(save()).toBeEnabled();
    fireEvent.change(input(), { target: { value: '𠮷'.repeat(33) } });
    expect(input()).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText('accountIdentity.errors.nicknameLength')).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(api).not.toHaveBeenCalled();
});

it('keeps historical original values unchanged and supports Escape', () => {
    const original = ` old nickname ${'𠮷'.repeat(40)}`;
    const callbacks = editor(original);
    expect(input()).toHaveValue(original);
    expect(input()).toHaveAttribute('aria-invalid', 'false');
    expect(save()).toBeDisabled();
    fireEvent.keyDown(input(), { key: 'Escape' });
    expect(callbacks.onCancel).toHaveBeenCalledTimes(1);
    expect(api).not.toHaveBeenCalled();
});

it('submits once and returns the actual saved profile', async () => {
    let finish!: (value: NicknameProfile) => void;
    api.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const callbacks = editor();
    fireEvent.change(input(), { target: { value: saved.user_name } });
    fireEvent.click(save());
    fireEvent.click(save());
    expect(api).toHaveBeenCalledTimes(1);
    expect(api).toHaveBeenCalledWith(saved.user_name);
    expect(screen.getByRole('button', { name: 'com_ui_cancel' })).toBeDisabled();
    await act(async () => finish(saved));
    expect(callbacks.onSaved).toHaveBeenCalledWith(saved);
});

it('preserves the draft after failure and allows retry', async () => {
    api.mockRejectedValueOnce(new Error('synthetic network failure'));
    const callbacks = editor();
    fireEvent.change(input(), { target: { value: saved.user_name } });
    fireEvent.click(save());
    await screen.findByText('accountIdentity.saveFailed');
    expect(input()).toHaveValue(saved.user_name);
    expect(callbacks.onSaved).not.toHaveBeenCalled();
    fireEvent.click(save());
    await waitFor(() => expect(callbacks.onSaved).toHaveBeenCalledWith(saved));
});
