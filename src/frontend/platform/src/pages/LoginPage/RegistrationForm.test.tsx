import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@bisheng/api-client';
import translations from '../../../public/locales/zh-Hans/bs.json';
import { registerApi } from '@/controllers/API/user';
import { showApiError } from '@/controllers/request';
import { handleEncrypt } from './utils';
import { RegistrationForm } from './RegistrationForm';

vi.mock('@/controllers/API/user', () => ({ registerApi: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('./utils', () => ({ handleEncrypt: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({
    t: (key: string) => key.split('.').reduce<unknown>((value, part) =>
        value && typeof value === 'object' ? (value as Record<string, unknown>)[part] : undefined, translations) ?? key,
}) }));

const captcha = { captcha_key: 'test-captcha-key', captcha: '', user_capthca: false };
const copy = translations.login.registration;
const nicknameValue = `${copy.nickname}Test`;
type RegisterResult = Awaited<ReturnType<typeof registerApi>>;
const registrationResult = {} as RegisterResult;
const account = () => screen.getByRole('textbox', { name: copy.account });
const nickname = () => screen.getByRole('textbox', { name: copy.nickname });
const password = () => screen.getByLabelText(translations.login.password, { exact: true });
const confirmation = () => screen.getByLabelText(translations.login.confirmPassword, { exact: true });
const input = (field: HTMLElement, value: string) => fireEvent.change(field, { target: { value } });
const submit = () => fireEvent.submit(account().closest('form')!);

function renderForm() {
    const callbacks = { onRefreshCaptcha: vi.fn(), onLogin: vi.fn(), onSuccess: vi.fn() };
    return { ...render(<RegistrationForm captcha={captcha} {...callbacks} />), ...callbacks };
}

function fillValid() {
    input(account(), 'CaseSensitive');
    input(nickname(), nicknameValue);
    input(password(), 'Abcd12_!');
    input(confirmation(), 'Abcd12_!');
}

beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(handleEncrypt).mockResolvedValue('encrypted-test-password');
    vi.mocked(registerApi).mockResolvedValue(registrationResult);
});
afterEach(cleanup);

it('opens field rules on click and closes them with Escape', () => {
    renderForm();
    const hint = screen.getByRole('button', { name: copy.accountRulesLabel });
    fireEvent.click(hint);
    expect(hint).toHaveAttribute('aria-expanded', 'true');
    expect(document.getElementById('registration-account-rules')).toHaveTextContent(copy.accountRules);
    fireEvent.keyDown(account(), { key: 'Escape' });
    expect(hint).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('registration-account-rules')).toBeNull();
});

describe('RegistrationForm', () => {
    it('shows the requested placeholders, two rule triggers, and two neutral password bullets', () => {
        const { container } = renderForm();
        expect(account()).toHaveAttribute('placeholder', copy.accountPlaceholder);
        expect(nickname()).toHaveAttribute('placeholder', copy.nicknamePlaceholder);
        expect(screen.getByRole('button', { name: copy.accountRulesLabel })).toBeVisible();
        expect(screen.getByRole('button', { name: copy.nicknameRulesLabel })).toBeVisible();
        expect(container.querySelectorAll('[data-state="neutral"][data-rule]')).toHaveLength(2);
        expect(screen.getByText(copy.passwordStrength)).toBeVisible();
        expect(screen.getByText(copy.passwordChecks.composition)).toBeVisible();
        expect(container.querySelector('#registration-confirmation-check')).not.toBeInTheDocument();
        expect(screen.queryByText(copy.errors.confirmationMismatch)).not.toBeInTheDocument();
        expect(account()).toHaveAttribute('aria-invalid', 'false');
    });

    it('sanitizes input and paste-equivalent changes without truncating overlong values', () => {
        renderForm();
        input(account(), ' A\u00A0b\u200Bc ');
        input(nickname(), ` ${nicknameValue}\t\u3000 `);
        expect(account()).toHaveValue('Abc');
        expect(nickname()).toHaveValue(nicknameValue);
        input(account(), '_bad');
        expect(account()).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByText(copy.errors.accountStart)).toBeVisible();
        input(account(), 'a'.repeat(65));
        expect(account()).toHaveValue('a'.repeat(65));
        expect(screen.getByText(copy.errors.accountLength)).toBeVisible();
        input(account(), 'a'.repeat(64));
        expect(account()).toHaveAttribute('aria-invalid', 'false');
        expect(screen.queryByText(copy.errors.accountLength)).not.toBeInTheDocument();
        input(nickname(), copy.nickname[0].repeat(33));
        expect(nickname()).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByText(copy.errors.nicknameLength)).toBeVisible();
    });

    it('filters whitespace after an IME commit', () => {
        renderForm();
        fireEvent.compositionEnd(nickname(), { target: { value: `IME\u3000${nicknameValue}` } });
        expect(nickname()).toHaveValue(`IME${nicknameValue}`);
    });

    it('updates requirements and confirmation when either password changes', () => {
        const { container } = renderForm();
        input(password(), 'A');
        expect(container.querySelector('[data-rule="length"]')).toHaveAttribute('data-state', 'fail');
        expect(container.querySelector('[data-rule="composition"]')).toHaveAttribute('data-state', 'fail');
        input(password(), 'Abcd12_!');
        input(confirmation(), 'Abcd12_!');
        expect(container.querySelectorAll('[data-state="pass"][data-rule]')).toHaveLength(2);
        expect(confirmation()).toHaveAttribute('aria-invalid', 'false');
        input(password(), 'Changed1!');
        expect(confirmation()).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByText(copy.errors.confirmationMismatch)).toBeVisible();
        input(confirmation(), 'Changed1!');
        expect(confirmation()).toHaveAttribute('aria-invalid', 'false');
        expect(screen.queryByText(copy.errors.confirmationMismatch)).not.toBeInTheDocument();
        input(password(), '');
        expect(container.querySelectorAll('#registration-password-checks [data-state="neutral"]')).toHaveLength(2);
    });

    it.each(['abcd123!', 'ABCD123!', 'Abcdefg!', 'Abcdef12'])(
        'keeps the combined check unmet when any character class is missing: %s', value => {
            const { container } = renderForm();
            input(password(), value);
            expect(container.querySelector('[data-rule="length"]')).toHaveAttribute('data-state', 'pass');
            expect(container.querySelector('[data-rule="composition"]')).toHaveAttribute('data-state', 'fail');
        },
    );

    it('checks length independently from the combined character requirement', () => {
        const { container } = renderForm();
        input(password(), 'Aa1!');
        expect(container.querySelector('[data-rule="length"]')).toHaveAttribute('data-state', 'fail');
        expect(container.querySelector('[data-rule="composition"]')).toHaveAttribute('data-state', 'pass');
    });

    it('reveals and hides either password without submitting or changing its value', () => {
        renderForm();
        fillValid();
        const toggles = screen.getAllByRole('button', { name: translations.sharedUi.showPassword });
        fireEvent.click(toggles[0]);
        expect(password()).toHaveAttribute('type', 'text');
        expect(password()).toHaveValue('Abcd12_!');
        expect(confirmation()).toHaveAttribute('type', 'password');
        fireEvent.click(screen.getByRole('button', { name: translations.sharedUi.hidePassword }));
        expect(password()).toHaveAttribute('type', 'password');
        fireEvent.click(toggles[1]);
        expect(confirmation()).toHaveAttribute('type', 'text');
        expect(confirmation()).toHaveValue('Abcd12_!');
        expect(registerApi).not.toHaveBeenCalled();
    });

    it('blocks invalid submissions and focuses the first invalid field', () => {
        renderForm();
        submit();
        expect(registerApi).not.toHaveBeenCalled();
        expect(handleEncrypt).not.toHaveBeenCalled();
        expect(account()).toHaveFocus();
        expect(screen.getByText(copy.errors.accountRequired)).toBeVisible();
        fillValid();
        input(account(), '@bad');
        submit();
        expect(registerApi).not.toHaveBeenCalled();
    });

    it('preserves account case and locks duplicate submissions until completion', async () => {
        let finish!: (value: RegisterResult) => void;
        vi.mocked(registerApi).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
        const callbacks = renderForm();
        fillValid();
        submit();
        submit();
        await waitFor(() => expect(registerApi).toHaveBeenCalledTimes(1));
        expect(registerApi).toHaveBeenCalledWith(nicknameValue, 'CaseSensitive', 'encrypted-test-password', 'test-captcha-key', undefined);
        await act(async () => finish(registrationResult));
        expect(callbacks.onSuccess).toHaveBeenCalledOnce();
    });

    it('keeps the form values after an API failure and enables retry', async () => {
        const failure = new Error('test server rejection');
        vi.mocked(registerApi).mockRejectedValueOnce(failure);
        const callbacks = renderForm();
        fillValid();
        submit();
        await waitFor(() => expect(showApiError).toHaveBeenCalledWith(failure));
        expect(account()).toHaveValue('CaseSensitive');
        expect(password()).toHaveValue('Abcd12_!');
        expect(callbacks.onRefreshCaptcha).toHaveBeenCalledOnce();
        expect(screen.getByRole('button', { name: translations.login.registerButton })).toBeEnabled();
    });

    it('displays backend field errors and clears them when that field changes', async () => {
        vi.mocked(registerApi).mockRejectedValueOnce(new ApiError({ status_code: 10622 }, { message: 'password rejected' }));
        renderForm(); fillValid(); submit();
        await screen.findByText('api_errors:10622');
        expect(password()).toHaveAttribute('aria-invalid', 'true');
        input(password(), 'Abcd12_!New');
        expect(screen.queryByText('api_errors:10622')).not.toBeInTheDocument();
        expect(password()).toHaveAttribute('aria-invalid', 'false');
    });

    it('explains the existing password upper bound even when both strength bullets pass', () => {
        renderForm(); input(password(), `Abcd12_!${'x'.repeat(121)}`);
        expect(password()).toHaveAttribute('aria-invalid', 'true');
        expect(screen.getByText(copy.errors.passwordLength)).toBeVisible();
    });
});
