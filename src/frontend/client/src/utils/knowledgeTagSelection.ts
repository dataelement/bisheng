import type { SelectedOrgKb } from '~/store/modeltype';

/** User-selected tags are fixed retrieval constraints, independent of model tool arguments. */
export function knowledgeSpaceTagFilters(selections: SelectedOrgKb[]): Record<string, number> | undefined {
  const tagged = selections.filter(item => item.type === 'space' && item.tag);
  if (!tagged.length) return undefined;
  return Object.fromEntries(tagged.map(item => [item.id, item.tag!.id]));
}
