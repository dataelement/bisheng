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
