export function extractApiStatusCode(error: any): number | null {
    const codeRaw =
        error?.statusCode ??
        error?.status_code ??
        error?.code ??
        error?.response?.data?.status_code ??
        error?.response?.data?.code;

    const code = typeof codeRaw === "string" ? parseInt(codeRaw, 10) : Number(codeRaw);
    return Number.isFinite(code) ? code : null;
}

export function createApiStatusError(payload: any): Error & { statusCode?: number } {
    const code = extractApiStatusCode(payload);
    const error = new Error(
        payload?.status_message ??
        payload?.message ??
        `API request failed${code ? ` (${code})` : ""}`
    ) as Error & { statusCode?: number };

    if (code != null) {
        error.statusCode = code;
    }

    return error;
}
