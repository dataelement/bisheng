/**
 * F004 (design §7 items 1, 6) — messages a run never read and gave back.
 *
 * When the user stops a run, or a relay run cannot be created, the backend
 * takes the unread messages out of the inbox, deletes their question rows and
 * returns them as `unread_messages`: in the terminal event (`run_stopped`,
 * `run_failed`) and, for a stop that ended the run itself, in the stop
 * response. Both can deliver the same message, so every message is taken once
 * by `message_id`.
 *
 * Pure reducers over `ConversationRunState`; the store wires them to actions.
 */
import type { ConversationRunState } from './runStore';

/** One entry of `unread_messages`. */
export interface RunUnreadMessage {
    message_id: string;
    text: string;
    files?: unknown[];
}

const MAX_RETURNED_IDS = 200;

/** Read `unread_messages` out of an event's `data` or a stop response. Never throws. */
export function unreadMessagesOf(source: unknown): RunUnreadMessage[] {
    const list = (source as { unread_messages?: unknown } | null | undefined)?.unread_messages;
    if (!Array.isArray(list)) return [];
    const out: RunUnreadMessage[] = [];
    for (const item of list) {
        const raw = item as { message_id?: unknown; text?: unknown; files?: unknown } | null;
        if (!raw || raw.message_id == null || raw.message_id === '') continue;
        out.push({
            message_id: String(raw.message_id),
            text: typeof raw.text === 'string' ? raw.text : '',
            ...(Array.isArray(raw.files) ? { files: raw.files } : {}),
        });
    }
    return out;
}

/**
 * Take returned messages: they stop being "queued" and wait in
 * `returnedMessages` until the page has removed their rows. A message that was
 * already taken (same `message_id`) is ignored.
 */
export function reduceUnreadMessages(conv: ConversationRunState, messages: RunUnreadMessage[]): ConversationRunState {
    const seen = new Set(conv.returnedIds);
    const fresh: RunUnreadMessage[] = [];
    for (const message of messages) {
        if (seen.has(message.message_id)) continue;
        seen.add(message.message_id);
        fresh.push(message);
    }
    if (fresh.length === 0) return conv;
    const queuedMessages = { ...conv.queuedMessages };
    for (const message of fresh) delete queuedMessages[message.message_id];
    return {
        ...conv,
        queuedMessages,
        returnedMessages: [...conv.returnedMessages, ...fresh],
        returnedIds: [...conv.returnedIds, ...fresh.map((m) => m.message_id)].slice(-MAX_RETURNED_IDS),
    };
}

/** Text of returned messages in send order, one blank line between two messages. */
export function joinReturnedText(messages: RunUnreadMessage[]): string {
    return messages
        .map((m) => m.text.trim())
        .filter(Boolean)
        .join('\n\n');
}

/** The returned text goes before what the input box already holds. */
export function mergeReturnedText(returned: string, current: string): string {
    if (!returned) return current;
    return current.trim() ? `${returned}\n\n${current}` : returned;
}

/**
 * The page handled the waiting returned messages. Those whose row was on
 * screen (`shownIds`) hand their text to the input box (`draftReturn`); the
 * others belong to an earlier visit of the conversation (the event stream
 * replays an ended run) and are dropped.
 */
export function reduceResolveReturned(conv: ConversationRunState, shownIds: ReadonlySet<string>): ConversationRunState {
    if (conv.returnedMessages.length === 0) return conv;
    const text = joinReturnedText(conv.returnedMessages.filter((m) => shownIds.has(m.message_id)));
    const draftReturn = text ? (conv.draftReturn ? `${conv.draftReturn}\n\n${text}` : text) : conv.draftReturn;
    return { ...conv, returnedMessages: [], draftReturn };
}

/** The input box took the returned text. */
export function reduceClearDraftReturn(conv: ConversationRunState): ConversationRunState {
    return conv.draftReturn ? { ...conv, draftReturn: null } : conv;
}
