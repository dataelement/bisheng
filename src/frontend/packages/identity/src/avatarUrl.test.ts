import { describe, expect, it } from 'vitest';
import { resolveUserAvatarUrl } from './rules';

describe('resolveUserAvatarUrl', () => {
    const signedPath = '/object/bisheng/avatar/2/photo.png?X-Amz-Signature=a%2Bb';

    it.each([
        [signedPath, '/workspace', `/workspace${signedPath}`],
        [signedPath.slice(1), '/workspace/', `/workspace${signedPath}`],
        [`/workspace${signedPath}`, '/workspace', `/workspace${signedPath}`],
        ['/bisheng/avatar/2/old.png?signature=old', '', '/bisheng/avatar/2/old.png?signature=old'],
        [signedPath, '/', signedPath],
        ['https://files.example.com/avatar.png', '/workspace', 'https://files.example.com/avatar.png'],
        ['//files.example.com/avatar.png', '/workspace', '//files.example.com/avatar.png'],
        ['  ', '/workspace', undefined],
        [null, '', undefined],
    ])('resolves %s under %s', (value, prefix, expected) => {
        expect(resolveUserAvatarUrl(value, prefix)).toBe(expected);
    });
});
