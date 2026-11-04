import type { KnowledgeSpace } from '~/api/knowledge';
import { groupHomeSpaces, homeTimestamp, mergePinnedOrder, sortHomeSpaces } from './homeSpaces';

function space(id: string, overrides: Partial<KnowledgeSpace> = {}): KnowledgeSpace {
  return {
    id, name: id, creator: '', creatorId: '', memberCount: 0, fileCount: 0, totalFileCount: 0,
    visibility: 'private' as KnowledgeSpace['visibility'], role: 'member' as KnowledgeSpace['role'],
    isPinned: false, createdAt: '', updatedAt: '', tags: [], isReleased: false, ...overrides,
  };
}

describe('knowledge home real-list projection', () => {
  it('deduplicates overlaps and retains department precedence and action source', () => {
    const groups = groupHomeSpaces([space('1'), space('2')], [space('2'), space('3'), space('3')], [space('1')]);
    expect(groups.all.map(({ space, source }) => [space.id, source])).toEqual([
      ['1', 'department'], ['2', 'created'], ['3', 'joined'],
    ]);
    expect([groups.department.length, groups.created.length, groups.joined.length]).toEqual([1, 1, 1]);
  });

  it('does not turn missing IDs or an empty API response into cards', () => {
    expect(groupHomeSpaces([space('')], [], []).all).toEqual([]);
    expect(groupHomeSpaces([], [], []).all).toEqual([]);
  });

  it('globally sorts merged creation dates, keeping pins first without mutating API arrays', () => {
    const groups = groupHomeSpaces([space('1', { createdAt: '2026-01-01' })],
      [space('2', { createdAt: '2026-03-01' })], [space('3', { isPinned: true })]);
    expect(sortHomeSpaces(groups.all, 'create_time').map(({ space }) => space.id)).toEqual(['3', '2', '1']);
    expect(groups.all.map(({ space }) => space.id)).toEqual(['3', '1', '2']);
  });

  it('uses actual update dates and deterministic IDs for ties or missing dates', () => {
    const items = groupHomeSpaces([space('10'), space('2'), space('4', { updatedAt: '2026-04-01 12:00:00' })], [], []).all;
    expect(sortHomeSpaces(items, 'update_time').map(({ space }) => space.id)).toEqual(['4', '2', '10']);
    expect(homeTimestamp('not-a-date')).toBe(0);
  });

  it('keeps pin priority under name sorting and alphabetizes the remaining real names', () => {
    const items = groupHomeSpaces([space('1', { name: 'Zulu', isPinned: true }), space('2', { name: 'Beta' }), space('3', { name: 'Alpha' })], [], []).all;
    expect(sortHomeSpaces(items, 'name').map(({ space }) => space.id)).toEqual(['1', '3', '2']);
  });

  it('keeps explicit pin order independent of every selected field and reordered API input', () => {
    const items = groupHomeSpaces([
      space('1', { name: 'Alpha', isPinned: true, createdAt: '2026-03-01' }),
      space('2', { name: 'Zulu', isPinned: true, createdAt: '2026-01-01' }),
      space('3', { name: 'Beta' }),
    ], [], []).all;
    for (const sort of ['name', 'create_time', 'update_time'] as const) {
      expect(sortHomeSpaces(items, sort, ['2', '1']).map(({ space }) => space.id)).toEqual(['2', '1', '3']);
      expect(sortHomeSpaces([...items].reverse(), sort, ['2', '1']).map(({ space }) => space.id)).toEqual(['2', '1', '3']);
    }
  });

  it('restores normal sorting on unpin and retains the previous rank on rollback', () => {
    const items = groupHomeSpaces([space('1', { name: 'Alpha', isPinned: true }),
      space('2', { name: 'Zulu', isPinned: true }), space('3', { name: 'Beta' })], [], []).all;
    const unpinned = items.map((item) => item.space.id === '2' ? { ...item, space: { ...item.space, isPinned: false } } : item);
    expect(sortHomeSpaces(unpinned, 'name', ['2', '1']).map(({ space }) => space.id)).toEqual(['1', '3', '2']);
    expect(sortHomeSpaces(items, 'name', ['2', '1']).map(({ space }) => space.id)).toEqual(['2', '1', '3']);
    expect(mergePinnedOrder(['2', '1'], ['1', '2', '4', '4'])).toEqual(['2', '1', '4']);
  });
});
