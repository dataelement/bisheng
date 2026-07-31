/**
 * Remembers which content the user had ticked for quick Q&A, per location.
 *
 * The pick is a property of *where you are*, not of the conversation: leaving a
 * folder and coming back should find the same files ticked, and picking a
 * different set in another folder must not disturb it. So entries are keyed by
 * (space, folder) and live in localStorage — this is a convenience, never a
 * source of truth, so anything unreadable or expired is silently discarded.
 *
 * Entries expire 7 days after they were last written. Reading prunes whatever
 * has gone stale, so the store cannot grow without bound from folders the user
 * visited once.
 */
const STORAGE_KEY_PREFIX = 'bs:';
const STORAGE_KEY_SUFFIX = ':ksQaSelection';
const TTL_MS = 7 * 24 * 60 * 60 * 1000;

interface Entry {
    ids: string[];
    savedAt: number;
}

type Store = Record<string, Entry>;

/** Identifies one folder of one space; the space root is the empty folder id. */
export function quickQaLocationKey(spaceId: string, folderId?: string): string {
    return `${spaceId}::${folderId ?? ''}`;
}

function storageKey(userId: string | number): string {
    return `${STORAGE_KEY_PREFIX}${userId}${STORAGE_KEY_SUFFIX}`;
}

function readStore(userId: string | number): Store {
    try {
        const raw = localStorage.getItem(storageKey(userId));
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return {};
        const now = Date.now();
        const alive: Store = {};
        for (const [key, entry] of Object.entries(parsed as Store)) {
            if (!entry || !Array.isArray(entry.ids) || typeof entry.savedAt !== 'number') continue;
            if (now - entry.savedAt > TTL_MS) continue;
            alive[key] = { ids: entry.ids.map(String), savedAt: entry.savedAt };
        }
        return alive;
    } catch {
        // Corrupt or unavailable storage is the same as "nothing remembered".
        return {};
    }
}

function writeStore(userId: string | number, store: Store): void {
    try {
        localStorage.setItem(storageKey(userId), JSON.stringify(store));
    } catch {
        // Quota or private-mode failures must never break the picker.
    }
}

/** Ids ticked last time at this location; empty when nothing is remembered. */
export function readQuickQaSelection(userId: string | number | undefined, key: string): string[] {
    if (userId === undefined || userId === null) return [];
    return readStore(userId)[key]?.ids ?? [];
}

/**
 * Records the current pick, refreshing its 7-day life. An empty pick removes the
 * entry outright — clearing the selection is how the user says "stop restoring
 * this", so there must be nothing left to come back.
 */
export function writeQuickQaSelection(
    userId: string | number | undefined,
    key: string,
    ids: string[],
): void {
    if (userId === undefined || userId === null) return;
    const store = readStore(userId);
    if (ids.length === 0) {
        if (!(key in store)) return;
        delete store[key];
    } else {
        store[key] = { ids: ids.map(String), savedAt: Date.now() };
    }
    writeStore(userId, store);
}
