/**
 * Reading a business error out of a response, in one place.
 *
 * The channel and knowledge-space pages each carried their own copy of this,
 * and neither consulted the `api_errors` catalogue — so a code whose only copy
 * lives there showed as "API request failed (19015)" no matter how carefully
 * the message had been written in three languages. Anything the user should be
 * able to read has to come through `translateApiErrorMessage`.
 */

import { translateApiErrorMessage } from "~/api/request";

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

/** The response envelope the api_errors translator expects, from any shape. */
function toErrorEnvelope(input: unknown): { status_code: number | null; status_message: string; data: unknown } {
    const root = (input && typeof input === "object" ? input : {}) as ApiStatusLike;
    const responseData = root.response?.data as ApiStatusLike | undefined;
    const nested = root.data as ApiStatusLike | undefined;
    const messages = [
        responseData?.status_message,
        responseData?.message,
        nested?.status_message,
        nested?.message,
        root.status_message,
        root.message,
    ];
    const status_message = messages.find((value) => typeof value === "string" && value.trim()) as string | undefined;
    return {
        status_code: extractApiStatusCode(input),
        status_message: status_message ?? "",
        // Templated copy interpolates from here (`{{name}}` and friends).
        data: responseData?.data ?? nested?.data ?? nested ?? undefined,
    };
}

export function extractApiErrorMessage(input: unknown): string {
    const translated = translateApiErrorMessage(toErrorEnvelope(input));
    if (typeof translated === "string" && translated.trim()) return translated;
    return input instanceof Error ? input.message : "";
}

export function createApiStatusError(input: unknown): Error & { statusCode?: number; status_code?: number } {
    const code = extractApiStatusCode(input);
    const message =
        extractApiErrorMessage(input) || `API request failed${code != null ? ` (${code})` : ""}`;
    const error = new Error(message) as Error & { statusCode?: number; status_code?: number };
    if (code != null) {
        error.statusCode = code;
        error.status_code = code;
    }
    return error;
}
