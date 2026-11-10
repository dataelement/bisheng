// @vitest-environment node
import { expect, it } from 'vitest';
import { transformPrivateCitations } from './markers';
import type { ChatCitation } from './types';
const id = 'knowledgesearch_af2df1b';
const citations: ChatCitation[] = [{ citationId: id, type: 'rag', sourcePayload: { items: [{ itemId: '12' }, { itemId: '5' }, { itemId: '6' }] } }];
it('recovers bare registered chunk references into the same numbered citation protocol', () => {
  const result = transformPrivateCitations(`A${id}:12 B ${id}:5 C ${id}:6 D ${id}:12`, citations);
  expect(result.transformedContent).toBe(`A[citationref:${id}:12] B [citationref:${id}:5] C [citationref:${id}:6] D [citationref:${id}:12]`);
  expect(Object.values(result.citationMap).map(ref => ref.label)).toEqual([1, 2, 3]);
});
it('does not fabricate citations for unknown chunks, examples, code, or links', () => {
  const content = `unknown ${id}:99 other knowledgesearch_deadbeef:5 \`${id}:5\`\n\`\`\`\n${id}:6\n\`\`\`\n[link](https://example.com/${id}:5)`;
  expect(transformPrivateCitations(content, citations).transformedContent).toBe(content);
  expect(transformPrivateCitations(`${id}:5`).citationMap).toEqual({});
});
it('keeps reference-panel items in sync with the repaired inline markers', async () => {
  const { createCitationUtilities } = await import('./index');
  const utils = createCitationUtilities(key => key);
  const result = utils.buildCitationReferenceItems({ content: `A ${id}:5 B ${id}:6`, citations });
  expect(result).toHaveLength(1);
  expect(result[0].itemIds).toEqual(['5', '6']);
});
it('recovers the malformed separators returned by file Q&A without leaking protocol characters', () => {
  const citationId = 'knowledgesearch_15c85c1a';
  const registry: ChatCitation[] = [{ citationId, type: 'rag', sourcePayload: { items: ['10', '12', '27', '28', '29'].map(itemId => ({ itemId })) } }];
  const result = transformPrivateCitations(`A ${citationId}:27${citationId}:28${citationId}:27\nB ${citationId}:29\nC ${citationId}:10\nD ${citationId}:12`, registry);
  expect(result.transformedContent).toBe(`A [citationref:${citationId}:27][citationref:${citationId}:28][citationref:${citationId}:27]\nB [citationref:${citationId}:29]\nC [citationref:${citationId}:10]\nD [citationref:${citationId}:12]`);
  expect(Object.values(result.citationMap).map(ref => ref.label)).toEqual([1, 2, 3, 4, 5]);
});
it('preserves malformed references in code, links and unknown sources', () => {
  const content = `\`${id}:5\`\n~~~text\n${id}:6\n~~~\n[link](https://example.com/${id}:5) ${id}:99`;
  expect(transformPrivateCitations(content, citations).transformedContent).toBe(content);
});
