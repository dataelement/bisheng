import { describe, expect, it } from 'vitest';
import {
    characterCount, getPasswordChecks, stripIdentityWhitespace,
    validateAccount, validateNickname, validateNicknameChange, validatePassword,
} from './rules';

const cjk = String.fromCodePoint(0x4e2d);
const cjkPair = String.fromCodePoint(0x4e2d, 0x6587);

describe('account policy', () => {
    it.each(['a', '0', 'a'.repeat(64), 'AB001', 'ab001', '00033', 'A._-@9'])('accepts %s without rewriting', value => {
        expect(validateAccount(value)).toBeUndefined();
    });
    it.each(['', 'a'.repeat(65), '_a', '.a', '-a', '@a', cjkPair, 'a+b', ' a', 'a ', 'a\tb', 'a\u200bb'])('rejects invalid raw value %s', value => {
        expect(validateAccount(value)).toBeDefined();
    });
});

describe('nickname policy', () => {
    it.each([cjk, 'a'.repeat(32), cjk.repeat(32), '𠮷'.repeat(32), `${cjk}._-@`, '😀'])('accepts visible value %s', value => {
        expect(validateNickname(value)).toBeUndefined();
    });
    it.each(['', 'a'.repeat(33), ' a', 'a b', 'a\n', 'a\u3000b', 'a\u200bb', 'a\u2060b', 'a\x00b', 'a\ufe0f', '\ud800'])('rejects invalid value %s', value => {
        expect(validateNickname(value)).toBeDefined();
    });
    it('counts code points and leaves unchanged historical data valid', () => {
        expect(characterCount('𠮷'.repeat(32))).toBe(32);
        const historical = ` old name ${cjk.repeat(40)}`;
        expect(validateNicknameChange(historical, historical)).toBeUndefined();
        expect(validateNicknameChange('NewNickname', historical)).toBeUndefined();
        expect(validateNicknameChange('new name', historical)).toBe('whitespace');
    });
    it('filters spaces, pasted separators and zero width spaces', () => {
        expect(stripIdentityWhitespace(` A\t${cjk}\nB\u3000C\u200b\u2060 `)).toBe(`A${cjk}BC`);
    });
});

describe('password policy', () => {
    it.each([
        ['', false], ['Aa1!', false], ['Aa1!aaaa', true], ['a1!aaaaa', false],
        ['AA1!AAAA', false], ['Aa!!aaaa', false], ['Aa11aaaa', false],
        ['Aa1  aaaa', false], [`Aa1${cjkPair}aaaa`, false], ['Aa1_aaaa', true],
        ['Aa1😀aaaa', true], [`Aa1!${'a'.repeat(124)}`, true], [`Aa1!${'a'.repeat(125)}`, false],
    ] as const)('validates %s', (value, expected) => {
        expect(validatePassword(value) === undefined).toBe(expected);
    });
    it('keeps all checks neutral before input', () => {
        expect(Object.values(getPasswordChecks(''))).toEqual(['neutral', 'neutral', 'neutral', 'neutral', 'neutral']);
    });
});
