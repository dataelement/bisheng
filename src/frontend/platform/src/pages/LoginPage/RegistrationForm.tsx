import { Button, Input, PasswordInput, toast } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { isApiError } from '@bisheng/api-client';
import { useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { IdentityRuleHint } from '@/components/bs-comp/identity/identityInput';
import { registerApi } from '@/controllers/API/user';
import { showApiError } from '@/controllers/request';
import { handleEncrypt } from './utils';
import {
    PASSWORD_REQUIREMENTS, getPasswordChecks, stripRegistrationWhitespace,
    validateRegistration, type CheckState, type RegistrationErrors, type RegistrationField, type RegistrationValues,
} from './registrationRules';

interface RegistrationFormProps {
    captcha: { captcha_key: string; captcha: string; user_capthca: boolean };
    onRefreshCaptcha: () => void;
    onLogin: () => void;
    onSuccess: () => void;
}

interface RequirementCheckProps {
    label: string;
    state: CheckState;
    name: string;
}

function RequirementCheck({ label, state, name }: RequirementCheckProps) {
    const { t } = useTranslation();
    const color = state === 'pass' ? 'text-blue-500' : 'text-text-3';
    return (
        <li className={`flex items-baseline gap-2 ${color}`} data-rule={name} data-state={state}>
            <span className="size-1 shrink-0 self-start rounded-full bg-current mt-2" aria-hidden />
            <span>{label}</span>
            <span className="sr-only">{t(`login.registration.states.${state}`)}</span>
        </li>
    );
}

export function RegistrationForm({ captcha, onRefreshCaptcha, onLogin, onSuccess }: RegistrationFormProps) {
    const { t } = useTranslation();
    const [values, setValues] = useState<RegistrationValues>({ account: '', nickname: '', password: '', confirmation: '' });
    const [touched, setTouched] = useState<Partial<Record<RegistrationField, boolean>>>({});
    const [expandedRule, setExpandedRule] = useState<'account' | 'nickname' | null>(null);
    const [serverErrors, setServerErrors] = useState<RegistrationErrors>({});
    const [submitted, setSubmitted] = useState(false);
    const [loading, setLoading] = useState(false);
    const submitting = useRef(false);
    const captchaRef = useRef<HTMLInputElement>(null);
    const fieldRefs = useRef<Partial<Record<RegistrationField, HTMLInputElement | null>>>({});
    const errors = validateRegistration(values);
    const passwordChecks = getPasswordChecks(values.password);
    const compositionCheck: CheckState = !values.password ? 'neutral' :
        PASSWORD_REQUIREMENTS.filter(requirement => requirement !== 'length')
            .every(requirement => passwordChecks[requirement] === 'pass') ? 'pass' : 'fail';
    const visibleError = (field: RegistrationField) =>
        serverErrors[field] || (values[field] || touched[field] || submitted ? errors[field] : undefined);
    const markTouched = (field: RegistrationField) => setTouched(previous => ({ ...previous, [field]: true }));

    const handleIdentityChange = (field: 'account' | 'nickname', input: HTMLInputElement, composing = false) => {
        const raw = input.value;
        const value = composing ? raw : stripRegistrationWhitespace(raw);
        const caret = stripRegistrationWhitespace(raw.slice(0, input.selectionStart ?? raw.length)).length;
        if (raw !== value) input.value = value;
        setValues(previous => ({ ...previous, [field]: value }));
        if (value !== values[field]) setServerErrors(previous => ({ ...previous, [field]: undefined }));
        if (raw !== value) requestAnimationFrame(() => {
            if (input.isConnected && document.activeElement === input) input.setSelectionRange(caret, caret);
        });
    };

    const handleIdentityInput = (field: 'account' | 'nickname', event: ChangeEvent<HTMLInputElement>) => {
        const nativeEvent = event.nativeEvent as InputEvent;
        handleIdentityChange(field, event.currentTarget, nativeEvent.isComposing);
    };

    const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (submitting.current) return;
        setSubmitted(true);
        const invalidField = (Object.keys(values) as RegistrationField[]).find(field => errors[field]);
        if (invalidField) {
            fieldRefs.current[invalidField]?.focus();
            return;
        }
        if (captcha.user_capthca && !captchaRef.current?.value) {
            toast.show({ type: 'warning', message: t('login.pleaseEnterCaptcha') });
            captchaRef.current?.focus();
            return;
        }
        submitting.current = true;
        setLoading(true);
        setServerErrors({});
        try {
            const encrypted = await handleEncrypt(values.password);
            await registerApi(values.nickname, values.account, encrypted, captcha.captcha_key, captchaRef.current?.value);
            toast.show({ type: 'success', message: t('login.registrationSuccess') });
            onSuccess();
        } catch (error) {
            if (isApiError(error)) {
                const fields: Record<number, RegistrationField> = { 10612: 'account', 10613: 'account', 10614: 'nickname', 10622: 'password' };
                const field = fields[error.status_code ?? 0];
                if (field) setServerErrors({ [field]: `api_errors:${error.status_code}` });
            }
            showApiError(error);
        } finally {
            submitting.current = false;
            setLoading(false);
            onRefreshCaptcha();
        }
    };

    const renderIdentityField = (field: 'account' | 'nickname') => {
        const error = visibleError(field);
        const label = t(`login.registration.${field}`);
        return (
            <div className="grid gap-1.5">
                <Input
                    size="medium" id={`registration-${field}`} aria-label={label}
                    ref={input => { fieldRefs.current[field] = input; }}
                    value={values[field]} onChange={event => handleIdentityInput(field, event)}
                    onCompositionEnd={event => handleIdentityChange(field, event.currentTarget)}
                    onBlur={() => markTouched(field)} disabled={loading}
                    placeholder={t(`login.registration.${field}Placeholder`)}
                    title={t(`login.registration.${field}Placeholder`)}
                    status={error ? 'error' : 'default'} aria-invalid={Boolean(error)}
                    aria-describedby={[
                        error ? `registration-${field}-error` : '',
                        expandedRule === field ? `registration-${field}-rules` : '',
                    ].filter(Boolean).join(' ') || undefined}
                    autoCapitalize="none" autoCorrect="off" spellCheck={false}
                    autoComplete={field === 'account' ? 'username' : 'nickname'}
                    suffix={
                        <IdentityRuleHint field={field} expanded={expandedRule === field} controls={`registration-${field}-rules`}
                            content={t(`login.registration.${field}Rules`)} label={t(`login.registration.${field}RulesLabel`)}
                            disabled={loading} onToggle={() => setExpandedRule(previous => previous === field ? null : field)} />
                    }
                />
                {error && <p id={`registration-${field}-error`} className="text-caption text-danger" aria-live="polite">{t(error)}</p>}
                {expandedRule === field && <p id={`registration-${field}-rules`} className="text-caption text-text-3">
                    {t(`login.registration.${field}Rules`)}
                </p>}
            </div>
        );
    };

    return (
        <form className="grid gap-3" onSubmit={handleSubmit} noValidate onKeyDown={event => {
            if (event.key === 'Escape' && expandedRule) {
                setExpandedRule(null);
                event.stopPropagation();
            }
        }}>
            {renderIdentityField('account')}
            {renderIdentityField('nickname')}
            <div className="grid gap-1.5">
                <PasswordInput size="medium" id="registration-password" aria-label={t('login.password')}
                    ref={input => { fieldRefs.current.password = input; }}
                    value={values.password} onChange={event => {
                        setValues(previous => ({ ...previous, password: event.target.value }));
                        setServerErrors(previous => ({ ...previous, password: undefined }));
                    }}
                    onBlur={() => markTouched('password')} disabled={loading}
                    placeholder={t('login.password')} autoComplete="new-password"
                    revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')}
                    status={visibleError('password') ? 'error' : 'default'}
                    aria-invalid={Boolean(visibleError('password'))} aria-describedby="registration-password-checks" />
                <div id="registration-password-checks" className="text-caption" aria-live="polite">
                    <p className="text-text-2">{t('login.registration.passwordStrength')}</p>
                    <ul className="mt-1 grid gap-0.5 pl-1">
                        <RequirementCheck name="length" label={t('login.registration.passwordChecks.length')}
                            state={passwordChecks.length} />
                        <RequirementCheck name="composition" label={t('login.registration.passwordChecks.composition')}
                            state={compositionCheck} />
                    </ul>
                </div>
                {visibleError('password') && (serverErrors.password || !values.password || errors.password?.endsWith('passwordLength')) &&
                    <p className="text-caption text-danger" aria-live="polite">{t(visibleError('password')!)}</p>}
            </div>
            <div className="grid gap-1.5">
                <PasswordInput size="medium" id="registration-confirmation" aria-label={t('login.confirmPassword')}
                    ref={input => { fieldRefs.current.confirmation = input; }}
                    value={values.confirmation} onChange={event => setValues(previous => ({ ...previous, confirmation: event.target.value }))}
                    onBlur={() => markTouched('confirmation')} disabled={loading}
                    placeholder={t('login.confirmPassword')} autoComplete="new-password"
                    revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')}
                    status={visibleError('confirmation') ? 'error' : 'default'}
                    aria-invalid={Boolean(visibleError('confirmation'))}
                    aria-describedby={visibleError('confirmation') ? 'registration-confirmation-error' : undefined} />
                {visibleError('confirmation') && <p id="registration-confirmation-error" className="text-caption text-danger" aria-live="polite">
                    {t(errors.confirmation!)}
                </p>}
            </div>
            {captcha.user_capthca && (
                <div className="flex items-center gap-4">
                    <Input size="medium" ref={captchaRef} aria-label={t('login.pleaseEnterCaptcha')}
                        placeholder={t('login.pleaseEnterCaptcha')} disabled={loading} />
                    <button type="button" aria-label={t('login.registration.refreshCaptcha')} onClick={onRefreshCaptcha} disabled={loading}>
                        <img src={`data:image/jpg;base64,${captcha.captcha}`} alt={t('login.pleaseEnterCaptcha')}
                            className="h-8 w-[120px] object-contain border border-border-base bg-fill-1" />
                    </button>
                </div>
            )}
            <div className="text-center">
                <Button type="button" color="primary" variant="link" size="small" onClick={onLogin} disabled={loading}>
                    {t('login.haveAccountLogin')}
                </Button>
            </div>
            <Button type="submit" size="large" className="mt-2" loading={loading}>{t('login.registerButton')}</Button>
        </form>
    );
}
