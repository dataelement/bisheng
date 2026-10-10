export function retainVisibleOrgKnowledgeSelections<
  T extends { id: string | number; type: string },
>(
  selections: T[],
  visibleOrgKnowledgeIds: Iterable<string | number>,
): T[] {
  const visibleIds = new Set(Array.from(visibleOrgKnowledgeIds, String));
  const retained = selections.filter(
    (item) => item.type !== "org" || visibleIds.has(String(item.id)),
  );
  return retained.length === selections.length ? selections : retained;
}
