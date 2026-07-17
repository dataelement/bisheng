import {
    formatStreamChatError,
    normalizeStreamChatError,
    parseStreamRetryEvent,
} from "./streamChatErrors";

describe("normalizeStreamChatError", () => {
    test("uses a safe Chinese business message instead of data.exception", () => {
        const message = normalizeStreamChatError({
            status_code: 429,
            status_message: "当日问答并发数已达上限",
            data: { exception: "provider token=secret failed" },
        });

        expect(message).toBe("当日问答并发数已达上限");
        expect(message).not.toContain("token=secret");
    });

    test("maps technical server errors to a generic Chinese message", () => {
        expect(normalizeStreamChatError({
            status_code: 500,
            status_message: "Server error",
            data: { exception: "database connection refused" },
        })).toBe("问答服务暂时不可用，请稍后重试。");
    });

    test("rejects a mixed Chinese status message containing technical details", () => {
        expect(normalizeStreamChatError({
            status_code: 500,
            status_message: "模型调用失败 token=secret",
        })).toBe("问答服务暂时不可用，请稍后重试。");
    });

    test("uses a generic Chinese fallback for unknown payloads", () => {
        expect(normalizeStreamChatError({ unexpected: true })).toBe("问答请求失败，请稍后重试。");
    });

    test("formats a structured model error as title plus a newline reason", () => {
        const error = formatStreamChatError({
            kind: "model",
            title: "模型调用失败",
            reason: "模型服务暂时不可用，请稍后重试。",
            retryable: true,
            data: { exception: "provider token=secret failed" },
        });

        expect(error).toEqual({
            kind: "model",
            title: "模型调用失败",
            reason: "模型服务暂时不可用，请稍后重试。",
            retryable: true,
            message: "模型调用失败\n模型服务暂时不可用，请稍后重试。",
        });
        expect(error.message).not.toContain("secret");
    });

    test("parses retry progress without trusting arbitrary server text", () => {
        expect(parseStreamRetryEvent({
            attempt: 2,
            max_attempts: 2,
            retry_after_ms: 1000,
            reason: "provider token=secret",
        })).toEqual({
            attempt: 2,
            maxAttempts: 2,
            retryAfterMs: 1000,
            message: "正在重试（2/2）",
        });
    });
});
