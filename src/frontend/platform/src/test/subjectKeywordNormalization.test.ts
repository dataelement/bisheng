import { describe, expect, it } from 'vitest';
import { normalizeSubjectKeyword as platformNormalize } from '@/components/bs-comp/selectComponent/useSubjectSearch';
import { normalizeSubjectKeyword as clientNormalize } from '../../../client/src/components/permission/useSubjectKeyword';

const whitespace = [9, 10, 11, 12, 13, 32, 0x85, 0xa0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000];
for (const [name, normalize] of [['platform', platformNormalize], ['client', clientNormalize]] as const) {
  describe(`${name} subject keyword whitespace`, () => {
    it.each(whitespace)('trims Unicode White_Space U+%i', code => {
      const character = String.fromCodePoint(code);
      expect(normalize(`${character}Alice${character}`)).toBe('Alice');
    });
    it('replaces internal line endings and preserves other internal whitespace', () => {
      expect(normalize('Alice\r\nBob\nCarol\tDan')).toBe('Alice Bob Carol\tDan');
    });
    it('preserves BOM and zero-width space because they are not Unicode White_Space', () => {
      expect(normalize('\uFEFFAlice\uFEFF')).toBe('\uFEFFAlice\uFEFF');
      expect(normalize('\u200BAlice\u200B')).toBe('\u200BAlice\u200B');
    });
  });
}
