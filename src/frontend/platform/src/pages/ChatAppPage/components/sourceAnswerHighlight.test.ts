import { expect, it } from 'vitest';
import { highlightSourceAnswer } from './sourceAnswerHighlight';

it.each([[], [''], ['<script>', '&', '"', "'"], ['[', '(', '\\', '.*']].map(keywords => ({ keywords })))('escapes all answer markup with keywords $keywords', ({ keywords }) => {
    const answer = '<script>synthetic</script> & " \' [ ( \\ .*';
    const element = document.createElement('p');
    element.innerHTML = highlightSourceAnswer(answer, keywords);
    expect(element.textContent).toBe(answer);
    expect([...element.children].every(child => child.tagName === 'SPAN' && child.attributes.length === 0)).toBe(true);
});

it('chooses longer overlapping literals and does not interpret replacement syntax', () => {
    expect(highlightSourceAnswer('abc ab $&', ['ab', 'abc', '$&', 'ab'])).toBe('<span>abc</span> <span>ab</span> <span>$&amp;</span>');
});
