export type CheckState = 'neutral' | 'pass' | 'fail';
export type PasswordRequirement = 'length' | 'uppercase' | 'lowercase' | 'number' | 'symbol';
export type IdentityError =
    | 'accountRequired' | 'accountLength' | 'accountStart' | 'accountCharacters'
    | 'nicknameRequired' | 'nicknameLength' | 'nicknameInvisible' | 'whitespace'
    | 'passwordRequired' | 'passwordLength' | 'passwordPolicy';

export const PASSWORD_REQUIREMENTS: PasswordRequirement[] = ['length', 'uppercase', 'lowercase', 'number', 'symbol'];
const WHITESPACE = /[\s\p{Z}\u200B\u2060]/gu;
const INVISIBLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Default_Ignorable_Code_Point}]/u;

export function stripIdentityWhitespace(value: string): string {
    return value.replace(WHITESPACE, '');
}

export function characterCount(value: string): number {
    return Array.from(value).length;
}

export function validateAccount(value: string): IdentityError | undefined {
    if (!value) return 'accountRequired';
    if (stripIdentityWhitespace(value) !== value) return 'whitespace';
    if (characterCount(value) > 64) return 'accountLength';
    if (!/^[A-Za-z0-9]/.test(value)) return 'accountStart';
    if (!/^[A-Za-z0-9._@-]+$/.test(value)) return 'accountCharacters';
    return undefined;
}

export function validateNickname(value: string): IdentityError | undefined {
    if (!value) return 'nicknameRequired';
    if (stripIdentityWhitespace(value) !== value) return 'whitespace';
    if (INVISIBLE.test(value)) return 'nicknameInvisible';
    if (characterCount(value) > 32) return 'nicknameLength';
    return undefined;
}

export function validateNicknameChange(value: string, original: string): IdentityError | undefined {
    return value === original ? undefined : validateNickname(value);
}

export function getPasswordChecks(value: string): Record<PasswordRequirement, CheckState> {
    const satisfied: Record<PasswordRequirement, boolean> = {
        length: characterCount(value) >= 8,
        uppercase: /[A-Z]/.test(value),
        lowercase: /[a-z]/.test(value),
        number: /[0-9]/.test(value),
        symbol: /[\p{P}\p{S}]/u.test(value),
    };
    return Object.fromEntries(PASSWORD_REQUIREMENTS.map(requirement => [
        requirement, value ? (satisfied[requirement] ? 'pass' : 'fail') : 'neutral',
    ])) as Record<PasswordRequirement, CheckState>;
}

export function validatePassword(value: string): IdentityError | undefined {
    if (!value) return 'passwordRequired';
    if (characterCount(value) > 128) return 'passwordLength';
    return PASSWORD_REQUIREMENTS.every(requirement => getPasswordChecks(value)[requirement] === 'pass') ?
        undefined : 'passwordPolicy';
}

export function getConfirmationCheck(password: string, confirmation: string): CheckState {
    return !confirmation ? 'neutral' : password === confirmation ? 'pass' : 'fail';
}
