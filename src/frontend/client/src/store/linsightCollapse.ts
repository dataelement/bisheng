/**
 * Linsight task-mode collapse persistence (F7).
 *
 * Group-level expand/collapse state for the execution timeline
 * (DeepStepGroup / SubagentTeamGroup / SubagentTrack) is persisted to
 * sessionStorage so that toggling a group open/closed survives a page refresh
 * and switching between conversations within the same tab.
 *
 * This is PURELY client UI state — it is never sent to the backend and issues
 * NO HTTP (constitution C7). Persistence is opt-in per group via a stable key
 * (the first step/agent callId, or the subagent namespace).
 *
 * Storage model: one Recoil atomFamily keyed by the group's stable id. The
 * stored value is a tri-state:
 *   - undefined → the user has never toggled this group; the consumer falls
 *     back to its own `defaultOpen` (running → open, completed → collapsed).
 *   - true / false → an explicit user choice, restored on refresh / session
 *     switch.
 * sessionStorage failures (private mode quota, disabled storage) degrade
 * gracefully to in-memory atom state — the UI still works, it just doesn't
 * persist across reloads.
 */
import { useCallback } from 'react';
import { atomFamily, useRecoilState } from 'recoil';

const STORAGE_PREFIX = 'linsightCollapse:';

/** Read one persisted collapse flag. Returns undefined when absent/unreadable. */
function readPersisted(key: string): boolean | undefined {
    try {
        const raw = sessionStorage.getItem(STORAGE_PREFIX + key);
        if (raw === null) return undefined;
        return raw === '1';
    } catch {
        // sessionStorage unavailable (private mode / disabled) — fall back to memory.
        return undefined;
    }
}

/** Persist one collapse flag. Silently no-ops when storage is unavailable. */
function writePersisted(key: string, open: boolean): void {
    try {
        sessionStorage.setItem(STORAGE_PREFIX + key, open ? '1' : '0');
    } catch {
        // Ignore — in-memory atom state still reflects the toggle this session.
    }
}

/**
 * Per-group persisted collapse flag. `undefined` = no explicit user choice yet
 * (consumer uses its own default). The effect seeds from sessionStorage on
 * mount and writes back on every change.
 */
const collapseStateFamily = atomFamily<boolean | undefined, string>({
    key: 'linsightCollapseStateFamily',
    default: undefined,
    effects: (key: string) => [
        ({ setSelf, onSet }) => {
            const saved = readPersisted(key);
            if (saved !== undefined) setSelf(saved);
            onSet((next) => {
                if (next === undefined) return; // never persist the "unset" sentinel
                writePersisted(key, next);
            });
        },
    ],
});

/**
 * Persisted collapse state for a single timeline group.
 *
 * @param key         Stable group id (first step/agent callId, or namespace).
 * @param defaultOpen Open state to use until the user toggles (running → true,
 *                    completed → false for history review).
 * @returns `[open, setOpen]` — `open` is the persisted value when present,
 *          otherwise `defaultOpen`; `setOpen` records an explicit choice (which
 *          is persisted to sessionStorage via the atom effect).
 */
export function useCollapseState(
    key: string,
    defaultOpen: boolean,
): [boolean, (next: boolean) => void] {
    const [persisted, setPersisted] = useRecoilState(collapseStateFamily(key));
    const open = persisted ?? defaultOpen;
    const setOpen = useCallback(
        (next: boolean) => setPersisted(next),
        [setPersisted],
    );
    return [open, setOpen];
}
