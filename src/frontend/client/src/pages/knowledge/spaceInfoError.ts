import { translateApiErrorMessage } from "~/api/request";

/** The space genuinely is not there, or is not this caller's to open. */
const SPACE_IS_GONE_CODES = new Set([
    18000, // Knowledge Space does not exist
    18040, // the caller may not view it
]);

export interface SpaceInfoFailure {
    /** Send the user back to the square, rather than leaving them on a dead page. */
    leaveSpace: boolean;
    messageKey: "com_knowledge.space_invalid_or_deleted" | "com_knowledge.space_load_failed";
    /** Server wording when it has some, so the toast says what actually happened. */
    message?: string;
}

/**
 * Decide what a failed space-detail load means.
 *
 * This used to be a bare `catch`: every failure became "该知识空间已失效或被删除"
 * followed by a bounce to the square. That reads as data loss, and it hid real
 * faults — disabling the upload_file action in the Permission Catalog made the
 * detail endpoint answer 25001 for every space, and every user was told their
 * spaces had been deleted.
 *
 * Only the server saying the space is absent (18000) or closed to this caller
 * (18040) justifies leaving the page. Anything else is our fault, not the
 * space's: say so and stay put, so a retry is one refresh away and the failure
 * stays visible instead of looking like a deletion.
 */
export function resolveSpaceInfoFailure(error: unknown): SpaceInfoFailure {
    const payload = error as { status_code?: unknown; status_message?: unknown; response?: { data?: unknown } };
    const fromResponse = payload?.response?.data as Record<string, unknown> | undefined;
    const source =
        payload?.status_code != null
            ? { status_code: payload.status_code, status_message: payload.status_message }
            : fromResponse;
    const code = Number((source as Record<string, unknown> | undefined)?.["status_code"]);

    if (Number.isFinite(code) && SPACE_IS_GONE_CODES.has(code)) {
        return { leaveSpace: true, messageKey: "com_knowledge.space_invalid_or_deleted" };
    }
    return {
        leaveSpace: false,
        messageKey: "com_knowledge.space_load_failed",
        message: source ? translateApiErrorMessage(source) || undefined : undefined,
    };
}
