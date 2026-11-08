import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@bisheng/api-client";
import { createInstance } from "i18next";
import request from "@/controllers/request";
import { deleteMarketWorkbench, previewWorkbenchBundle } from "@/controllers/API/dshWorkbenches";
import en from "../../../../public/locales/en-US/dshMarket.json";
import zh from "../../../../public/locales/zh-Hans/dshMarket.json";
import ja from "../../../../public/locales/ja/dshMarket.json";
import enErrors from "../../../../../packages/locales/src/api_errors/en.json";
import zhErrors from "../../../../../packages/locales/src/api_errors/zh-Hans.json";
import jaErrors from "../../../../../packages/locales/src/api_errors/ja.json";
import { workbenchPreviewErrorMessage } from "./workbenchPreviewError";

const notices = vi.hoisted(() => vi.fn());
vi.mock("@bisheng/ui", () => ({ notification: { open: notices } }));
const adapter = request.defaults.adapter;
afterEach(() => { request.defaults.adapter = adapter; notices.mockClear(); });

async function translator(lang = "en-US") {
    const i18n = createInstance();
    await i18n.init({ lng: lang, defaultNS: "dshMarket", resources: {
        "en-US": { dshMarket: en, api_errors: enErrors },
        "zh-Hans": { dshMarket: zh, api_errors: zhErrors },
        ja: { dshMarket: ja, api_errors: jaErrors },
    }, interpolation: { escapeValue: false } });
    return i18n.t;
}

async function previewFailure(data: unknown, statusMessage = "Validation failed") {
    request.defaults.adapter = async config => ({ config, status: 200, statusText: "OK", headers: {},
        data: { status_code: 26205, status_message: statusMessage, data } });
    return previewWorkbenchBundle(new File(["archive"], "workbench.tgz"), 7, new AbortController().signal)
        .catch((failure: unknown) => failure);
}

describe("workbench preview diagnostics through the wrapped request", () => {
    it("deletes with the displayed revision, explicit tenant and abort signal", async () => {
        const controller = new AbortController();
        request.defaults.adapter = async config => {
            expect(config.method).toBe("delete");
            expect(config.url).toBe("/api/v1/dsh/market/admin/workbenches/workbench-id");
            expect(config.params).toEqual({ revision: 7 });
            expect(config.headers.get("x-dsh-market-tenant")).toBe("9");
            expect(config.signal).toBe(controller.signal);
            return { config, status: 200, statusText: "OK", headers: {}, data: {
                status_code: 200, data: { id: "workbench-id", deleted: true },
            } };
        };
        expect(await deleteMarketWorkbench("workbench-id", 7, 9, controller.signal)).toEqual({ id: "workbench-id", deleted: true });
    });
    it.each([
        ["WORKBENCH_ARCHIVE_LIMIT", "WB02", "archive", "Expanded archive exceeds the allowed size"],
        ["WORKBENCH_ARCHIVE_INVALID", "WB01", "archive", "Invalid gzip stream"],
        ["WORKBENCH_CONFIG_INVALID", "WB09", "config.model", "Expected an object"],
    ])("shows the precise %s reason, rule and field", async (code, rule, field, message) => {
        const failure = await previewFailure({ code, rule, field, message });
        expect(failure).toBeInstanceOf(ApiError);
        expect(failure).toMatchObject({ kind: "business", status_code: 26205, data: { code, rule, field, message } });
        const result = workbenchPreviewErrorMessage(failure, await translator());
        const heading = code === "WORKBENCH_ARCHIVE_LIMIT" ? enErrors.WORKBENCH_ARCHIVE_LIMIT
            : code === "WORKBENCH_ARCHIVE_INVALID" ? enErrors.WORKBENCH_ARCHIVE_INVALID
                : enErrors.WORKBENCH_VALIDATION_FAILED;
        expect(result?.split("\n")[0]).toBe(heading);
        expect(result).toContain(message);
        expect(result).toContain("Field: " + field);
        expect(result).toContain("Rule: " + rule);
        expect(result).toContain(code);
        expect(result).not.toContain("connection");
        expect(notices).not.toHaveBeenCalled();
    });

    it("uses status_message when the structured reason is missing", async () => {
        const failure = await previewFailure({ code: "WORKBENCH_CONFIG_INVALID", rule: "WB09", field: null }, "Missing config");
        const result = workbenchPreviewErrorMessage(failure, await translator());
        expect(result).toContain("Reason: Missing config");
        expect(result).not.toContain("Field:");
    });

    it.each(["en-US", "zh-Hans", "ja"])("localizes diagnostics in %s without losing backend detail", async lang => {
        const failure = await previewFailure({ code: "WORKBENCH_ARCHIVE_INVALID", rule: "WB01", field: "archive", message: "Invalid gzip stream" });
        const result = workbenchPreviewErrorMessage(failure, await translator(lang));
        expect(result).toContain("Invalid gzip stream");
        expect(result).toContain("WB01");
        expect(result).not.toMatch(/dshMarket:|api_errors:|{{/);
        expect(result).toContain(({ "en-US": en, "zh-Hans": zh, ja })[lang as "en-US"].workbenchPreview.field.replace("{{field}}", "archive"));
    });

    it.each([
        ["ERR_NETWORK", "Could not reach the server"],
        ["ECONNABORTED", "timed out"],
    ])("keeps %s distinct from archive validation", async (code, expected) => {
        request.defaults.adapter = async config => { throw Object.assign(new Error("transport"), { config, code }); };
        const failure = await previewWorkbenchBundle(new File(["archive"], "workbench.tgz"), 7, new AbortController().signal).catch((error: unknown) => error);
        const result = workbenchPreviewErrorMessage(failure, await translator());
        expect(result).toContain(expected);
        expect(result).not.toContain("validation");
        expect(notices).not.toHaveBeenCalled();
    });

    it("preserves HTTP failures even if their body contains validator metadata", async () => {
        const data = { status_code: 26205, data: { code: "WORKBENCH_ARCHIVE_INVALID", message: "Do not treat HTTP errors as content" } };
        request.defaults.adapter = async config => { throw Object.assign(new Error("HTTP failure"), { config, response: { status: 502, data } }); };
        const failure = await previewWorkbenchBundle(new File(["archive"], "workbench.tgz"), 7, new AbortController().signal).catch((error: unknown) => error);
        expect(failure).toMatchObject({ kind: "http", httpStatus: 502 });
        const result = workbenchPreviewErrorMessage(failure, await translator());
        expect(result).toContain("HTTP 502");
        expect(result).not.toContain("Do not treat");
    });

    it.each(["en-US", "zh-Hans", "ja"])("shows the 100 MiB HTTP 413 hint in %s without changing its kind", async lang => {
        const failure = new ApiError({ response: { status: 413, data: "Request Entity Too Large" } }, { message: "HTTP error" });
        expect(failure.kind).toBe("http");
        const message = workbenchPreviewErrorMessage(failure, await translator(lang));
        expect(message).toBe(({ "en-US": en, "zh-Hans": zh, ja })[lang as "en-US"].workbenchPreview.tooLarge);
        expect(message).toContain("100 MiB");
        expect(failure.kind).toBe("http");
    });

    it("does not surface arbitrary backend text outside the validator contract", async () => {
        const failure = new ApiError({ status_code: 500, status_message: "internal traceback" }, { message: "Server error" });
        expect(workbenchPreviewErrorMessage(failure, await translator())).toBe("Server error");
    });

    it("ignores malformed diagnostics and handles unexpected errors", async () => {
        const t = await translator();
        expect(workbenchPreviewErrorMessage(new Error("internal"), t)).toBe(en.workbenchPreview.invalidResponse);
        const failure = await previewFailure({ code: {}, rule: [], field: {}, message: {} });
        expect(workbenchPreviewErrorMessage(failure, t)).not.toContain("[object Object]");
    });

    it("does not report cancellation as failure", async () => {
        expect(workbenchPreviewErrorMessage(new ApiError({ code: "ERR_CANCELED" }, { message: "canceled" }), await translator())).toBeNull();
    });
});
