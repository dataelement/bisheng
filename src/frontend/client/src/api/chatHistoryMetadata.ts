import type { ChatMessage } from './chatMessageTypes';
import { parseFailureInfo } from '~/utils/failureInfo';

export interface StreamHistoryItem {
    id: number;
    is_bot: boolean;
    message: string; // JSON string: {"content": "...", "reasoning_content": "..."} or {"query": "...", "tags": [...]}
    category: string; // "question" | "answer"
    type: string;
    flow_id: string;
    chat_id: string;
    user_id: number;
    user_name: string;
    flow_name: string;
    create_time: string;
    update_time: string;
    sender: string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    [key: string]: any;
}

export function applyRecoveryMetadata(message: ChatMessage, rawExtra: unknown): void {
    let extra = rawExtra;
    if (typeof extra === "string") {
        try {
            extra = JSON.parse(extra);
        } catch {
            extra = null;
        }
    }
    if (!extra || typeof extra !== "object") return;
    const metadata = extra as Record<string, unknown>;
    message.failureInfo = parseFailureInfo(metadata.failure_info);
    if (metadata.error === true || message.failureInfo) message.error = true;
    if (typeof metadata.error_type === "string") message.errorType = metadata.error_type;
    if (typeof metadata.error_code === "number") message.errorCode = metadata.error_code;
    if (typeof metadata.error_msg === "string") message.errorText = metadata.error_msg;
    if (typeof metadata.detail === "string") message.errorDetail = metadata.detail;
    if (typeof metadata.execution_id === "string") message.executionId = metadata.execution_id;
    if (typeof metadata.attempt_id === "string") message.attemptId = metadata.attempt_id;
    if (typeof metadata.recovery_subject_id === "string") {
        message.recoverySubjectId = metadata.recovery_subject_id;
    }
    if (typeof metadata.model_id === "string" || typeof metadata.model_id === "number") {
        message.modelId = metadata.model_id;
    }
    if (
        metadata.rate_limit_state === "normal"
        || metadata.rate_limit_state === "recovering"
        || metadata.rate_limit_state === "busy"
    ) {
        message.rateLimitState = metadata.rate_limit_state;
    }
    if (typeof metadata.unfinished === "boolean") message.unfinished = metadata.unfinished;
    if (metadata.error_type === "rate_limit") {
        message.error = true;
        message.errorType = "rate_limit";
    }
    if (typeof metadata.resume_mode === "string") message.resumeMode = metadata.resume_mode;
}

/** Parse a stream-format history item → ChatMessage */
export function parseStreamHistoryItem(raw: StreamHistoryItem): ChatMessage {
    let displayText = "";
    try {
        const parsed = JSON.parse(raw.message);
        if (raw.is_bot) {
            // Bot messages: { content, reasoning_content }
            const reasoning = parsed.reasoning_content || "";
            const content = parsed.content || "";
            displayText = reasoning
                ? `:::thinking\n${reasoning}\n:::\n${content}`
                : content;
        } else {
            // User messages: { query, tags? }
            displayText = parsed.query || parsed.text || raw.message;
            // Re-encode the first tag (if any) into the same `:::tag {...}:::`
            // prefix the live send path uses, so the user bubble can render
            // the chip after a history reload.
            const firstTag = Array.isArray(parsed.tags) ? parsed.tags[0] : null;
            if (firstTag && typeof firstTag.name === "string") {
                const tagJson = JSON.stringify({
                    id: Number(firstTag.id) || 0,
                    name: firstTag.name,
                });
                displayText = `:::tag ${tagJson}:::\n${displayText}`;
            }
        }
    } catch {
        displayText = raw.message || "";
    }

    const message: ChatMessage = {
        messageId: String(raw.id),
        parentMessageId: "",
        conversationId: raw.chat_id || "",
        sender: raw.is_bot ? "AI" : "User",
        text: displayText,
        isCreatedByUser: !raw.is_bot,
        createdAt: raw.create_time,
        error: false,
        flow_name: raw.flow_name,
        liked: raw.liked,
    };
    applyRecoveryMetadata(message, raw.extra);
    return message;
}
