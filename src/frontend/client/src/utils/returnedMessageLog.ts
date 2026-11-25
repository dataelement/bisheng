/**
 * F004 (design §7 items 1, 6) — which returned messages this browser already
 * handed to the input box.
 *
 * The event stream replays an ended run for an hour, so the `unread_messages`
 * of a stop reach the page again on every later visit and after a reload. The
 * rows of those messages are deleted on the server, so the message list cannot
 * tell "handed over before" from "not handed over yet". This log can: an id is
 * written when its text goes to the input box and is skipped from then on.
 *
 * The ids are inbox ids (unique across conversations); only the newest
 * `MAX_IDS` are kept. Without usable storage the log is empty and nothing is
 * remembered across reloads.
 */
const STORAGE_KEY = 'bs:run:returnedHandled';
const MAX_IDS = 200;

function readIds(): string[] {
    try {
        const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
        return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [];
    } catch {
        return [];
    }
}

/** Ids of the returned messages already handed to the input box. */
export function handedReturnedIds(): Set<string> {
    return new Set(readIds());
}

/** Record that the text of these returned messages went to the input box. */
export function rememberHandedReturnedIds(ids: Iterable<string>): void {
    const known = readIds();
    const seen = new Set(known);
    for (const id of ids) {
        if (seen.has(id)) continue;
        seen.add(id);
        known.push(id);
    }
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(known.slice(-MAX_IDS)));
    } catch {
        /* storage is unavailable (private window, quota): the ids are not remembered */
    }
}
