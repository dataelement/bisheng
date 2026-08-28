import {
  markAgentToolsTouched,
  persistAgentTools,
  readStoredAgentTools,
  restoreAgentTools,
} from './agentToolsMemory';

/**
 * The rule under test is the one that broke "后台配了默认工具，工作台没勾上":
 * a remembered selection may override the admin default only when the user
 * actually made one.
 */
describe('readStoredAgentTools', () => {
  it('adopts a selection the user made', () => {
    expect(readStoredAgentTools('[{"id":16}]', true)).toEqual([{ id: 16 }]);
  });

  it('adopts an EMPTY selection once the user has used the picker', () => {
    // Switching every tool off is a decision, and must survive a reload rather
    // than being re-seeded from the admin default on the next visit.
    expect(readStoredAgentTools('[]', true)).toEqual([]);
  });

  it('ignores the legacy empty snapshot written before the user chose anything', () => {
    // Older builds wrote this on the first visit for everyone; treating it as a
    // choice is what made the admin default unreachable forever.
    expect(readStoredAgentTools('[]', false)).toBeNull();
  });

  it('adopts a legacy NON-empty entry and does not lose the user their tools', () => {
    // No marker, but an entry with content can only have come from a real
    // toggle — dropping it would silently reset users on the upgrade.
    expect(readStoredAgentTools('[{"id":16}]', false)).toEqual([{ id: 16 }]);
  });

  it('falls back to the admin default when nothing is stored', () => {
    expect(readStoredAgentTools(null, false)).toBeNull();
    expect(readStoredAgentTools(null, true)).toBeNull();
  });

  it('falls back to the admin default on a corrupt or non-array entry', () => {
    expect(readStoredAgentTools('not json', true)).toBeNull();
    expect(readStoredAgentTools('{"id":16}', true)).toBeNull();
    expect(readStoredAgentTools('null', true)).toBeNull();
  });
});

/**
 * The storage wrappers are where the legacy migration actually happens, so they
 * are pinned separately. A minimal in-memory stub stands in for localStorage —
 * a key/value map is all these functions need.
 */
function useFakeStorage(seed: Record<string, string> = {}) {
  const store = new Map(Object.entries(seed));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- assigning over the global's readonly Storage type
  (globalThis as any).localStorage = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  return store;
}

describe('restoreAgentTools / persistAgentTools', () => {
  const USER = 7;
  const listKey = `bs:${USER}:selectedAgentTools`;
  const markKey = `bs:${USER}:agentToolsTouched`;

  it('restores nothing for a user who never chose, so admin defaults seed', () => {
    useFakeStorage();
    expect(restoreAgentTools(USER)).toBeNull();
  });

  it('discards the legacy empty snapshot — the bug being fixed', () => {
    useFakeStorage({ [listKey]: '[]' });
    expect(restoreAgentTools(USER)).toBeNull();
  });

  it('adopts a legacy non-empty entry and stamps it as the user choice', () => {
    const store = useFakeStorage({ [listKey]: '[{"id":16}]' });
    expect(restoreAgentTools(USER)).toEqual([{ id: 16 }]);
    // Stamped, so an all-off toggle later is remembered instead of re-judged.
    expect(store.get(markKey)).toBe('1');
  });

  it('does not persist until the user has used the picker', () => {
    const store = useFakeStorage();
    persistAgentTools(USER, [{ id: 16 }]);
    expect(store.has(listKey)).toBe(false);
  });

  it('persists once the picker has been used, empty selection included', () => {
    const store = useFakeStorage();
    markAgentToolsTouched(USER);
    persistAgentTools(USER, []);
    expect(store.get(listKey)).toBe('[]');
    // And that empty choice now survives a reload.
    expect(restoreAgentTools(USER)).toEqual([]);
  });

  it('is a no-op without a user id', () => {
    const store = useFakeStorage();
    markAgentToolsTouched(undefined);
    persistAgentTools(undefined, [{ id: 1 }]);
    expect(restoreAgentTools(undefined)).toBeNull();
    expect(store.size).toBe(0);
  });
});
