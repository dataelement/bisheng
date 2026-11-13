// @vitest-environment node
import { expect, it } from 'vitest';
import { hideStreamingCitations } from './streaming';

const id = 'knowledgesearch_15c85c1a';
it.each(['knowledgesearch_', 'websearch_', 'tempsearch_', 'articlesearch_'])('buffers every split of a %s reference without blocking following prose', prefix => {
  const ref = `${prefix}15c85c1a:29`;
  for (let length = 1; length <= ref.length; length++) {
    expect(hideStreamingCitations(`Answer ${ref.slice(0, length)}`)).toBe('Answer ');
  }
  expect(hideStreamingCitations(`Answer ${ref} Next paragraph.`)).toBe('Answer  Next paragraph.');
});
it('hides wrapped, adjacent and orphaned protocol markers', () => {
  expect(hideStreamingCitations(`A ${id}:27${id}:28 B ${id}:29 C`)).toBe('A  B  C');
  expect(hideStreamingCitations(`A ${id}:29\nNext paragraph.`)).toBe('A \nNext paragraph.');
});
it('buffers escaped protocol characters across delta boundaries', () => {
  const marker = '\\ue200';
  for (let length = 1; length <= marker.length; length++) {
    expect(hideStreamingCitations(`Answer ${marker.slice(0, length)}`)).toBe('Answer ');
  }
  expect(hideStreamingCitations(`Answer \\ue200${id}:29\\ue202 End.`)).toBe('Answer  End.');
});
it.each([
  `\`${id}:29\``,
  `\`\`${id}:29\`\``,
  `\`\`\`text\n${id}:29\n\`\`\``,
  `~~~text\n${id}:29\n~~~`,
  `    ${id}:29`,
  `\t${id}:29`,
  `[source ${id}:29](https://example.com)`,
  `[source](https://example.com/${id}:29)`,
  `https://example.com/${id}:29`,
  `[source](https://example.com/${id}:29`,
])('preserves code and links literally: %s', literal => {
  expect(hideStreamingCitations(`${literal}\nAnswer ${id}:29 End.`)).toBe(`${literal}\nAnswer  End.`);
});
it.each(['```text', '~~~text'])('preserves an unfinished %s code block until its closing fence arrives', fence => {
  const source = `${fence}\n${id}:29\nMore code.`;
  expect(hideStreamingCitations(source)).toBe(source);
});
it('restores ordinary suffix text as soon as it stops matching citation syntax', () => {
  expect(hideStreamingCitations('Answer know')).toBe('Answer ');
  expect(hideStreamingCitations('Answer knowledge is useful.')).toBe('Answer knowledge is useful.');
  expect(hideStreamingCitations('Answer knowledgesearch_settings.')).toBe('Answer knowledgesearch_settings.');
  expect(hideStreamingCitations(`Answer x${id}:29.3`)).toBe(`Answer x${id}:29.3`);
});
