const TECHNICAL_MESSAGE_PATTERN = /(?:traceback|exception|stack|provider|database|token|secret|api[_ -]?key|https?:\/\/|\/users\/|\/home\/)/i;

export type StreamErrorKind =
    | "model"
    | "retrieval"
    | "document"
    | "rate_limit"
    | "network"
    | "auth"
    | "config"
    | "system";

export interface StreamChatError {
    kind: StreamErrorKind;
    title: string;
    reason: string;
    retryable: boolean;
    message: string;
}

export interface StreamRetryProgress {
    attempt: number;
    maxAttempts: number;
    retryAfterMs: number;
    message: string;
}

const ERROR_COPY: Record<StreamErrorKind, { title: string; reason: string }> = {
    model: { title: "模型调用失败", reason: "模型服务暂时不可用，请稍后重试。" },
    retrieval: { title: "知识检索失败", reason: "暂时无法检索相关知识，请稍后重试。" },
    document: { title: "文档暂不可用", reason: "文档可能尚未就绪或已失效，请稍后再试。" },
    rate_limit: { title: "请求过于频繁", reason: "服务当前繁忙，请稍后重试。" },
    network: { title: "网络连接失败", reason: "连接问答服务超时或中断，请稍后重试。" },
    auth: { title: "认证或权限失败", reason: "当前账号无权执行此操作，请检查登录状态或权限。" },
    config: { title: "问答配置异常", reason: "问答模型或服务尚未正确配置，请联系管理员。" },
    system: { title: "问答服务异常", reason: "问答服务暂时不可用，请稍后重试。" },
};

const hasChineseText = (value: string): boolean => /[\u3400-\u9fff]/u.test(value);

const isSafeBusinessMessage = (value: unknown): value is string => {
    if (typeof value !== "string") return false;
    const message = value.trim();
    return Boolean(message)
        && message.length <= 160
        && hasChineseText(message)
        && !TECHNICAL_MESSAGE_PATTERN.test(message);
};

export const normalizeStreamChatError = (payload: unknown): string => {
    if (!payload || typeof payload !== "object") {
        return "问答请求失败，请稍后重试。";
    }

    const data = payload as Record<string, unknown>;
    if (isSafeBusinessMessage(data.status_message)) {
        return data.status_message.trim();
    }

    const statusCode = Number(data.status_code);
    if (statusCode >= 500) {
        return "问答服务暂时不可用，请稍后重试。";
    }
    if (statusCode === 429) {
        return "问答请求过于频繁，请稍后重试。";
    }

    return "问答请求失败，请稍后重试。";
};

const resolveErrorKind = (payload: Record<string, unknown>): StreamErrorKind => {
    if (typeof payload.kind === "string" && payload.kind in ERROR_COPY) {
        return payload.kind as StreamErrorKind;
    }
    const statusCode = Number(payload.status_code);
    if (statusCode === 429) return "rate_limit";
    if (statusCode === 401 || statusCode === 403) return "auth";
    return "system";
};

export const formatStreamChatError = (payload: unknown): StreamChatError => {
    const data = payload && typeof payload === "object"
        ? payload as Record<string, unknown>
        : {};
    const kind = resolveErrorKind(data);
    const fallback = ERROR_COPY[kind];
    const title = isSafeBusinessMessage(data.title) ? data.title.trim() : fallback.title;
    const reason = isSafeBusinessMessage(data.reason) ? data.reason.trim() : fallback.reason;
    return {
        kind,
        title,
        reason,
        retryable: data.retryable === true,
        message: `${title}\n${reason}`,
    };
};

export const parseStreamRetryEvent = (payload: unknown): StreamRetryProgress => {
    const data = payload && typeof payload === "object"
        ? payload as Record<string, unknown>
        : {};
    const maxAttempts = Math.max(1, Math.min(2, Number(data.max_attempts) || 2));
    const attempt = Math.max(1, Math.min(maxAttempts, Number(data.attempt) || 1));
    const retryAfterMs = Math.max(0, Math.min(30_000, Number(data.retry_after_ms) || 0));
    return {
        attempt,
        maxAttempts,
        retryAfterMs,
        message: `正在重试（${attempt}/${maxAttempts}）`,
    };
};
