import type { KnowledgeSpace } from '~/api/knowledge';

export type HomeSource = 'department' | 'created' | 'joined';
export type HomeCategory = 'all' | HomeSource;
export type HomeSort = 'create_time' | 'update_time' | 'name';
export type HomeSpace = { space: KnowledgeSpace; source: HomeSource };

/** Preserve department precedence, then resolve overlaps by stable ID. */
export function groupHomeSpaces(mine: KnowledgeSpace[], joined: KnowledgeSpace[], department: KnowledgeSpace[]): Record<HomeCategory, HomeSpace[]> {
  const seen = new Set<string>();
  const take = (spaces: KnowledgeSpace[], source: HomeSource) => spaces.flatMap((space) => {
    if (!space.id || seen.has(space.id)) return [];
    seen.add(space.id);
    return [{ space, source }];
  });
  const departments = take(department, 'department');
  const created = take(mine, 'created');
  const joinedSpaces = take(joined, 'joined');
  return { all: [...departments, ...created, ...joinedSpaces], department: departments, created, joined: joinedSpaces };
}

export function homeTimestamp(value: string): number {
  const time = Date.parse(value.replace(' ', 'T'));
  return Number.isFinite(time) ? time : 0;
}

/** Keep first-seen server pins stable until the API exposes their pin timestamps. */
export function mergePinnedOrder(order: readonly string[], pinnedIds: readonly string[]): readonly string[] {
  const known = new Set(order);
  const missing: string[] = [];
  for (const id of pinnedIds) {
    if (known.has(id)) continue;
    known.add(id);
    missing.push(id);
  }
  return missing.length ? [...order, ...missing] : order;
}

/** Pinned items use their own explicit newest-first order; only normal items use the selected sort. */
export function sortHomeSpaces(items: HomeSpace[], sort: HomeSort, pinnedOrder: readonly string[] = []): HomeSpace[] {
  const collator = new Intl.Collator(undefined, { sensitivity: 'base' });
  const orderedPins = mergePinnedOrder(pinnedOrder, items.filter(({ space }) => space.isPinned).map(({ space }) => space.id));
  const rank = new Map(orderedPins.map((id, index) => [id, index]));
  return [...items].sort((a, b) => {
    const pin = Number(b.space.isPinned) - Number(a.space.isPinned);
    if (pin) return pin;
    if (a.space.isPinned && b.space.isPinned) return rank.get(a.space.id)! - rank.get(b.space.id)!;
    const order = sort === 'name' ? collator.compare(a.space.name, b.space.name)
      : homeTimestamp(sort === 'create_time' ? b.space.createdAt : b.space.updatedAt)
      - homeTimestamp(sort === 'create_time' ? a.space.createdAt : a.space.updatedAt);
    return order || a.space.id.localeCompare(b.space.id, undefined, { numeric: true });
  });
}
