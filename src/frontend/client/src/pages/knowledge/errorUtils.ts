export function extractKnowledgeActionErrorMessage(input: unknown): string {
    const errorMessage = input instanceof Error ? input.message : "";
    if (!input || typeof input !== "object") return errorMessage;

    const root = input as {
        message?: unknown;
        status_message?: unknown;
        data?: { message?: unknown; status_message?: unknown };
        response?: { data?: { message?: unknown; status_message?: unknown } };
    };

    const candidates = [
        root.response?.data?.status_message,
        root.response?.data?.message,
        root.data?.status_message,
        root.data?.message,
        root.status_message,
        root.message,
        errorMessage,
    ];

    for (const candidate of candidates) {
        if (typeof candidate === "string" && candidate.trim()) return candidate;
    }
    return "";
}

/**
 * Whether the response interceptor has already shown this error to the user.
 *
 * Business errors on the skip403Redirect path are toasted centrally before the
 * promise rejects, so a caller that toasts again in its catch block shows the
 * same sentence twice.
 */
export function isKnowledgeActionErrorAlreadyNotified(input: unknown): boolean {
    if (!input || typeof input !== "object") return false;
    const statusCode = (input as { status_code?: unknown }).status_code;
    if (typeof statusCode !== "number") return false;
    return Boolean(extractKnowledgeActionErrorMessage(input));
}
