import { isApiError } from "@bisheng/api-client";
import type { TFunction } from "i18next";

function text(value: unknown): string {
    return typeof value === "string" ? value.trim() : "";
}

/** Keep transport failures separate from the workbench validator's public diagnostics. */
export function workbenchPreviewErrorMessage(failure: unknown, t: TFunction): string | null {
    if (!isApiError(failure)) return t("dshMarket:workbenchPreview.invalidResponse");
    if (failure.kind === "canceled") return null;
    if (failure.kind === "network") return t("dshMarket:workbenchPreview.network");
    if (failure.kind === "timeout") return t("dshMarket:workbenchPreview.timeout");
    if (failure.kind === "http") {
        if (failure.httpStatus === 413) return t("dshMarket:workbenchPreview.tooLarge");
        return t("dshMarket:workbenchPreview.http", { status: failure.httpStatus });
    }
    if (failure.kind === "invalid-response") return t("dshMarket:workbenchPreview.invalidResponse");

    const data = failure.data !== null && typeof failure.data === "object"
        ? failure.data as Record<string, unknown> : {};
    const code = text(data.code);
    if (failure.status_code !== 26205 || !code.startsWith("WORKBENCH_")) return failure.message;

    // Only this validator contract exposes backend reasons as user-facing content.
    const reason = text(data.message) || text(failure.status_message);
    const heading = code === "WORKBENCH_ARCHIVE_LIMIT" ? "api_errors:WORKBENCH_ARCHIVE_LIMIT"
        : code === "WORKBENCH_ARCHIVE_INVALID" ? "api_errors:WORKBENCH_ARCHIVE_INVALID"
            : "api_errors:WORKBENCH_VALIDATION_FAILED";
    const lines = [t(heading)];
    if (reason) lines.push(t("dshMarket:workbenchPreview.reason", { reason }));
    if (text(data.field)) lines.push(t("dshMarket:workbenchPreview.field", { field: text(data.field) }));
    if (text(data.rule)) lines.push(t("dshMarket:workbenchPreview.rule", { rule: text(data.rule) }));
    lines.push(t("dshMarket:workbenchPreview.code", { code }));
    return lines.join("\n");
}
