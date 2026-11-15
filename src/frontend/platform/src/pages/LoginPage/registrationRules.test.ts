import { describe, expect, it } from 'vitest';
import {
    characterCount, getConfirmationCheck, getPasswordChecks, stripRegistrationWhitespace,
    validateAccount, validateNickname, validateRegistration,
} from './registrationRules';

const cjk = String.fromCodePoint(0x540d);

describe('registration identity rules', () => {
    it('keeps account case and accepts the exact 1–64 character boundary', () => {
        expect(validateAccount('A')).toBeUndefined();
        expect(validateAccount('Case-sensitive_1.2@company')).toBeUndefined();
        expect(validateAccount('a'.repeat(64))).toBeUndefined();
        expect(validateAccount('a'.repeat(65))).toContain('accountLength');
        expect(stripRegistrationWhitespace('CaseSensitive')).toBe('CaseSensitive');
    });

    it.each(['.admin', '_admin', '-admin', '@admin'])('rejects a non-alphanumeric start: %s', account => {
        expect(validateAccount(account)).toContain('accountStart');
    });

    it.each(['A!', 'A/123', `A${cjk}`, 'A😀'])('rejects unsupported account characters: %s', account => {
        expect(validateAccount(account)).toContain('accountCharacters');
    });

    it('removes leading, internal, trailing, Unicode, and pasted whitespace', () => {
        const raw = ' A\tb\nc\r\nd\u00A0e\u2003f\u2028g\u2029h\u3000i\uFEFFj\u200Bk\u2060 ';
        expect(stripRegistrationWhitespace(raw)).toBe('Abcdefghijk');
        expect(validateAccount(raw)).toContain('whitespace');
        expect(validateNickname(raw)).toContain('whitespace');
        expect(stripRegistrationWhitespace(`${cjk}-😀`)).toBe(`${cjk}-😀`);
    });

    it('counts Unicode characters and enforces nickname visibility and boundaries', () => {
        expect(validateNickname(cjk)).toBeUndefined();
        expect(validateNickname(cjk.repeat(32))).toBeUndefined();
        expect(validateNickname(cjk.repeat(33))).toContain('nicknameLength');
        expect(characterCount('😀'.repeat(32))).toBe(32);
        expect(validateNickname('😀'.repeat(32))).toBeUndefined();
        expect(validateNickname('name\u202E')).toContain('nicknameInvisible');
        expect(validateNickname('')).toContain('nicknameRequired');
    });
});

describe('registration password checks', () => {
    it('starts neutral, evaluates each requirement separately, and returns to neutral when cleared', () => {
        expect(Object.values(getPasswordChecks(''))).toEqual(Array(5).fill('neutral'));
        expect(getPasswordChecks('A')).toEqual({ length: 'fail', uppercase: 'pass', lowercase: 'fail', number: 'fail', symbol: 'fail' });
        expect(Object.values(getPasswordChecks('Abcd12_!'))).toEqual(Array(5).fill('pass'));
        expect(Object.values(getPasswordChecks(''))).toEqual(Array(5).fill('neutral'));
    });

    it('does not count whitespace or a Chinese letter as a symbol', () => {
        expect(getPasswordChecks('Abcdef1 ').symbol).toBe('fail');
        expect(getPasswordChecks(`Abcdef1${cjk}`).symbol).toBe('fail');
        expect(getPasswordChecks('Abcdef1！').symbol).toBe('pass');
        expect(getPasswordChecks('A1a😀😀😀').length).toBe('fail');
    });

    it('re-evaluates confirmation against either password value', () => {
        expect(getConfirmationCheck('', '')).toBe('neutral');
        expect(getConfirmationCheck('Abcd12_!', '')).toBe('neutral');
        expect(getConfirmationCheck('Abcd12_!', 'wrong')).toBe('fail');
        expect(getConfirmationCheck('Abcd12_!', 'Abcd12_!')).toBe('pass');
        expect(getConfirmationCheck('Changed1!', 'Abcd12_!')).toBe('fail');
    });

    it('uses the same requirements to block submission', () => {
        const valid = { account: 'A', nickname: cjk, password: 'Abcd12_!', confirmation: 'Abcd12_!' };
        expect(Object.values(validateRegistration(valid)).every(error => !error)).toBe(true);
        expect(validateRegistration({ ...valid, password: 'Abcdef1 ', confirmation: 'Abcdef1 ' }).password).toContain('passwordRequirements');
        expect(validateRegistration({ ...valid, confirmation: '' }).confirmation).toContain('confirmationRequired');
    });
});
