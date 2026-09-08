import { fileAcceptToInputAccept, normalizeSuffixList } from './fileAcceptUtils';

// Regression guard. The two file forms disagree on the shape of `suffixes`:
// InputFormSkill hands over an array off the node template, InputForm hands over
// the joined string fileAcceptToInputAccept() returns. A consumer that assumed
// the array shape called .join(',') on the string and threw
// `join is not a function`, which is why the workflow form's upload field
// opened no picker — and, once the same call moved into render, why the whole
// form stopped rendering.
describe('normalizeSuffixList', () => {
  it('accepts the array shape the skill form passes', () => {
    expect(normalizeSuffixList(['.pdf', '.docx'])).toEqual(['.pdf', '.docx']);
  });

  it('accepts the joined string the workflow form passes', () => {
    expect(normalizeSuffixList('.pdf,.docx')).toEqual(['.pdf', '.docx']);
  });

  it('round-trips whatever fileAcceptToInputAccept produces', () => {
    const accept = fileAcceptToInputAccept(['file']);
    expect(accept).toEqual(expect.any(String));
    expect(normalizeSuffixList(accept).length).toBeGreaterThan(0);
    expect(normalizeSuffixList(accept).join(',')).toBe(accept);
  });

  it('tolerates spacing, empties and absence rather than throwing', () => {
    expect(normalizeSuffixList(' .pdf , .docx ,, ')).toEqual(['.pdf', '.docx']);
    expect(normalizeSuffixList('')).toEqual([]);
    expect(normalizeSuffixList(undefined)).toEqual([]);
    expect(normalizeSuffixList(null)).toEqual([]);
    expect(normalizeSuffixList([])).toEqual([]);
  });
});
