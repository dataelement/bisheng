import {
    getConfirmationCheck,
    stripIdentityWhitespace,
    validateAccount as validateIdentityAccount,
    validateNickname as validateIdentityNickname,
    validatePassword,
} from '@bisheng/identity';

export { characterCount, getPasswordChecks, getConfirmationCheck, PASSWORD_REQUIREMENTS } from '@bisheng/identity';
export type { CheckState, PasswordRequirement } from '@bisheng/identity';

export interface RegistrationValues {
    account: string;
    nickname: string;
    password: string;
    confirmation: string;
}

export type RegistrationField = keyof RegistrationValues;
export type RegistrationErrors = Partial<Record<RegistrationField, string>>;
const key = (name: string) => `login.registration.errors.${name}`;

export function stripRegistrationWhitespace(value: string): string {
    return stripIdentityWhitespace(value);
}

export function validateAccount(value: string): string | undefined {
    const error = validateIdentityAccount(value);
    return error ? key(error) : undefined;
}

export function validateNickname(value: string): string | undefined {
    const error = validateIdentityNickname(value);
    return error ? key(error) : undefined;
}

export function validateRegistration(values: RegistrationValues): RegistrationErrors {
    const passwordError = validatePassword(values.password);
    return {
        account: validateAccount(values.account),
        nickname: validateNickname(values.nickname),
        password: passwordError ? key(passwordError === 'passwordPolicy' ? 'passwordRequirements' : passwordError) : undefined,
        confirmation: !values.confirmation ? key('confirmationRequired') :
            getConfirmationCheck(values.password, values.confirmation) === 'pass' ? undefined : key('confirmationMismatch'),
    };
}
