import { translateApiErrorMessage } from "~/api/request";

/**
 * What to show when a download call fails.
 *
 * The download button is offered on every reviewed file and the server decides,
 * so a refusal is a normal outcome here rather than a bug. The permission check
 * answers business code 19000, which already carries a translation ("无权限。"),
 * and the response interceptor hands it to us on the rejected error. Showing the
 * generic "download failed" for that case would tell the user their network
 * hiccuped when in fact they are simply not allowed.
 *
 * Anything without a business code — a dropped connection, a malformed reply —
 * falls back to the caller's generic wording.
 */
export function resolveDownloadErrorMessage(error: unknown, fallback: string): string {
    const payload = error as { status_code?: unknown; status_message?: unknown; response?: { data?: unknown } };
    const fromResponse = payload?.response?.data as Record<string, unknown> | undefined;
    const source =
        payload?.status_code != null
            ? { status_code: payload.status_code, status_message: payload.status_message, data: fromResponse?.["data"] }
            : fromResponse;
    if (!source || (source as Record<string, unknown>)["status_code"] == null) return fallback;
    const translated = translateApiErrorMessage(source);
    return translated || fallback;
}
