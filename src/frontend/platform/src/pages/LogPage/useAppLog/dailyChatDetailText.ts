/** 工作台审计详情用的展示文案. 工具准备失败和真正的调用失败都保留原句. */

interface DailyHistoryMessage {
    text?: string;
    isCreatedByUser?: boolean;
}

interface DailyEvent {
    type?: string;
    content?: string;
    error?: string;
}

export function extractDailyDisplayText(msg: DailyHistoryMessage): string {
    const raw = msg?.text ?? "";
    if (typeof raw !== "string" || !raw) return "";
    const trimmed = raw.trim();
    if (!trimmed.startsWith("{")) return raw;

    let parsed: Record<string, unknown>;
    try {
        parsed = JSON.parse(trimmed);
    } catch {
        return raw;
    }
    if (!parsed || typeof parsed !== "object") return raw;

    if (msg.isCreatedByUser) {
        if (typeof parsed.query === "string") return parsed.query;
        if (typeof parsed.text === "string") return parsed.text;
        return raw;
    }

    const content =
        typeof parsed.msg === "string"
            ? parsed.msg
            : typeof parsed.content === "string"
                ? parsed.content
                : "";

    const events = Array.isArray(parsed.events) ? parsed.events as DailyEvent[] : [];
    let reasoning = "";
    if (Array.isArray(parsed.events)) {
        reasoning = events
            .filter((event) => event && event.type === "thinking")
            .map((event) => (typeof event?.content === "string" ? event.content : ""))
            .filter(Boolean)
            .join("\n\n");
    } else if (Array.isArray(parsed.thinking_segments) && parsed.thinking_segments.length) {
        reasoning = (parsed.thinking_segments as Array<{ content?: string }>)
            .map((segment) => (typeof segment?.content === "string" ? segment.content : ""))
            .filter(Boolean)
            .join("\n\n");
    } else if (typeof parsed.reasoning_content === "string") {
        reasoning = parsed.reasoning_content;
    }

    const toolErrors = toolFailureLines(events);
    const body = [toolErrors, content].filter(Boolean).join("\n\n");
    if (reasoning) return `:::thinking\n${reasoning}\n:::\n${body}`;
    return body || raw;
}

function toolFailureLines(events: DailyEvent[]): string {
    return events
        .filter((event) => event && event.type === "tool_call" && typeof event.error === "string" && event.error.trim())
        .map((event) => (event.error as string).trim())
        .join("\n\n");
}
