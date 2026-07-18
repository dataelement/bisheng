type ChatErrorPayload = {
    status_code?: number | string;
    status_message?: string;
    data?: Record<string, unknown>;
};

type Translate = (key: string, options?: Record<string, unknown>) => unknown;

function coerceErrorDetail(value: unknown): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value.trim();
    if (typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }
    if (Array.isArray(value)) {
        return value.map(coerceErrorDetail).filter(Boolean).join("; ");
    }
    if (typeof value === "object") {
        const detail = value as Record<string, unknown>;
        const preferredDetail = detail.message ?? detail.detail ?? detail.msg;
        if (preferredDetail !== undefined) return coerceErrorDetail(preferredDetail);

        try {
            return JSON.stringify(value);
        } catch {
            return String(value);
        }
    }
    return String(value);
}

export function resolveChatErrorMessage(
    payload: ChatErrorPayload | null | undefined,
    translate: Translate,
): string {
    const fallbackMessage = payload?.status_message || "error";
    const statusCode = payload?.status_code;

    const interpolationParams =
        payload?.data && typeof payload.data === "object" ? payload.data : {};
    const translatedMessage =
        statusCode === undefined || statusCode === null || statusCode === ""
            ? fallbackMessage
            : translate(`errors.${statusCode}`, {
                ...interpolationParams,
                defaultValue: fallbackMessage,
            });
    const summary =
        typeof translatedMessage === "string" && translatedMessage
            ? translatedMessage
            : fallbackMessage;
    const detailMessage = coerceErrorDetail(interpolationParams.exception);

    if (!detailMessage || summary.includes(detailMessage)) return summary;
    return `${summary}: ${detailMessage}`;
}
