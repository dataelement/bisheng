type ApiStatusLike = {
    statusCode?: unknown;
    status_code?: unknown;
    code?: unknown;
    status?: unknown;
    data?: unknown;
    response?: {
        data?: unknown;
        status?: unknown;
    };
    message?: unknown;
    status_message?: unknown;
};

function toStatusCode(value: unknown): number | null {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
}

export function extractApiStatusCode(input: unknown): number | null {
    if (!input || typeof input !== "object") return null;

    const root = input as ApiStatusLike;
    const responseData = root.response?.data as ApiStatusLike | undefined;
    const data = root.data as ApiStatusLike | undefined;
    const candidates = [
        root.statusCode,
        root.status_code,
        root.code,
        responseData?.statusCode,
        responseData?.status_code,
        responseData?.code,
        data?.statusCode,
        data?.status_code,
        data?.code,
        root.response?.status,
        root.status,
    ];

    for (const candidate of candidates) {
        const code = toStatusCode(candidate);
        if (code != null) return code;
    }
    return null;
}

export function createApiStatusError(input: unknown): Error & { statusCode?: number; status_code?: number } {
    const code = extractApiStatusCode(input);
    const root = (input && typeof input === "object" ? input : {}) as ApiStatusLike;
    const data = (root.response?.data || root.data || root) as ApiStatusLike;
    const message =
        typeof data.status_message === "string"
            ? data.status_message
            : typeof data.message === "string"
                ? data.message
                : `API request failed${code != null ? ` (${code})` : ""}`;
    const error = new Error(message) as Error & { statusCode?: number; status_code?: number };
    if (code != null) {
        error.statusCode = code;
        error.status_code = code;
    }
    return error;
}
