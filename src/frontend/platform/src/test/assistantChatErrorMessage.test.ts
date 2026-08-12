import { describe, expect, it, vi } from "vitest";

import { isBlockingChatError, resolveChatErrorMessage } from "@/components/bs-comp/chatComponent/chatErrorMessage";

describe("isBlockingChatError", () => {
    it("treats a deleted or offline assistant as blocking", () => {
        expect(isBlockingChatError({ status_code: 10420 })).toBe(true);
        expect(isBlockingChatError({ status_code: 10421 })).toBe(true);
    });

    it("treats runtime failures as retryable", () => {
        expect(isBlockingChatError({ status_code: 10499 })).toBe(false);
        expect(isBlockingChatError({ status_code: 10401 })).toBe(false);
        expect(isBlockingChatError({ status_message: "Connection failed" })).toBe(false);
        expect(isBlockingChatError(null)).toBe(false);
    });
});

describe("resolveChatErrorMessage", () => {
    it("uses the localized status-code message instead of the backend language", () => {
        const translate = vi.fn(() => "助手服务异常");

        const message = resolveChatErrorMessage(
            {
                status_code: 10499,
                status_message: "Assistant Service Exception",
            },
            translate,
        );

        expect(message).toBe("助手服务异常");
        expect(translate).toHaveBeenCalledWith("api_errors:10499", {
            defaultValue: "Assistant Service Exception",
        });
    });

    it("appends the backend exception to a generic localized error", () => {
        const translate = vi.fn(() => "助手服务异常");

        const message = resolveChatErrorMessage(
            {
                status_code: 10499,
                status_message: "Assistant Service Exception",
                data: {
                    exception:
                        "401 Client Error: PermissionDenied for url: https://api.bing.microsoft.com/v7.0/search",
                },
            },
            translate,
        );

        expect(message).toBe(
            "助手服务异常: 401 Client Error: PermissionDenied for url: https://api.bing.microsoft.com/v7.0/search",
        );
    });

    it("does not duplicate an exception already interpolated into the localized message", () => {
        const translate = vi.fn(
            (_key, options) => `助手上线失败: ${options?.exception}`,
        );

        const message = resolveChatErrorMessage(
            {
                status_code: 10401,
                status_message: "Assistant online failed",
                data: { exception: "model unavailable" },
            },
            translate,
        );

        expect(message).toBe("助手上线失败: model unavailable");
    });

    it("formats structured exception details", () => {
        const translate = vi.fn(() => "助手服务异常");

        const message = resolveChatErrorMessage(
            {
                status_code: 10499,
                status_message: "Assistant Service Exception",
                data: { exception: { message: "Tool authorization failed" } },
            },
            translate,
        );

        expect(message).toBe("助手服务异常: Tool authorization failed");
    });

    it("falls back to status_message when no status code is available", () => {
        const translate = vi.fn();

        expect(
            resolveChatErrorMessage(
                { status_message: "Connection failed" },
                translate,
            ),
        ).toBe("Connection failed");
        expect(translate).not.toHaveBeenCalled();
    });
});
