/**
 * SSE hook for v2.5 Agent-mode chat streaming.
 *
 * Backend event shape (ChatResponse): { category, type, message, chat_id, message_id? }.
 * Supported categories / types:
 *   agent_thinking / stream   → append delta to the open thinking event
 *   agent_thinking / end      → finalise duration_ms on the open thinking event
 *   agent_tool_call / start   → push a new inflight tool_call event
 *   agent_tool_call / end     → update the matching tool_call event with results/error
 *   agent_answer / stream     → append delta to responseText
 *   agent_answer / end        → stamp final responseText
 *
 * The hook maintains a single ordered `events` array (AgentEvent[]) that the
 * frontend renders directly — no segment_idx / after_segment cross-refs.
 *
 * Legacy / older payload shapes (`event: on_*_delta` and plain `text`) are
 * still accepted so old chat flows keep working.
 */
import { useEffect, useRef } from "react";
import { SSE } from "sse.js";
import type { AgentEvent, ChatMessage, ContentPart } from "~/api/chatApi";
import { getSSEUrl } from "~/api/chatApi";

/**
 * Structured update emitted as agent SSE events stream in. Consumers merge
 * these fields into the current assistant message.
 */
export interface AgentPatch {
    messageId?: string;
    /** Running text of the final answer (accumulates across stream deltas). */
    text?: string;
    /** Full ordered event log — thinking + tool_call entries in arrival order. */
    events?: AgentEvent[];
    /** Category hint — set to 'agent_answer' once the agent stream lands. */
    category?: string;
    /** True once the final `agent_answer.end` event has been received. */
    finalised?: boolean;
}

export interface SSESubmission {
    payload: Record<string, any>;
    userMessage: ChatMessage;
    /** Optional SSE endpoint URL override. Defaults to workstation SSE URL. */
    sseUrl?: string;
    onCreated: (conversationId: string, userMsg: ChatMessage) => void;
    /** Legacy callback — emits an envelope string for old `:::thinking:::` UI. */
    onMessage: (text: string, messageId: string) => void;
    /**
     * v2.5 native update — fires on every relevant agent_* SSE event with the
     * latest structured snapshot. Supersedes `onMessage` for new flows.
     * `onMessage` is still invoked for backward compat (tests / legacy bubble).
     */
    onAgentUpdate?: (patch: AgentPatch) => void;
    onFinal: (data: any) => void;
    onError: (error: string) => void;
    onStart: () => void;
    onEnd: () => void;
}

export default function useAiChatSSE(submission: SSESubmission | null) {
    const sseRef = useRef<any>(null);

    useEffect(() => {
        if (!submission) return;

        const {
            payload,
            userMessage,
            onCreated,
            onMessage,
            onAgentUpdate,
            onFinal,
            onError,
            onStart,
            onEnd,
        } = submission;

        // ---- Agent-mode accumulators ---------------------------------------
        const events: AgentEvent[] = [];
        let currentThinkingIdx: number | null = null;
        const toolCallIdx = new Map<string, number>();
        let responseText = "";
        let currentMessageId = "";

        /** Concatenate every thinking event's content (for the legacy envelope). */
        const thinkingText = () =>
            events
                .filter((e): e is Extract<AgentEvent, { type: "thinking" }> =>
                    e.type === "thinking",
                )
                .map((e) => e.content)
                .join("\n\n");

        const legacyEnvelope = () => {
            const tt = thinkingText();
            return tt ? `:::thinking\n${tt}\n:::\n${responseText}` : responseText;
        };
        const emitLegacy = () =>
            onMessage(legacyEnvelope(), currentMessageId);
        const emitAgent = (patch: AgentPatch) => {
            if (!onAgentUpdate) return;
            onAgentUpdate({
                messageId: currentMessageId || undefined,
                ...patch,
            });
        };
        const snapshot = (): AgentEvent[] => events.map((e) => ({ ...e }));

        const sseUrl = submission.sseUrl || getSSEUrl();
        const sse = new SSE(sseUrl, {
            payload: JSON.stringify(payload),
            headers: { "Content-Type": "application/json" },
        });
        sseRef.current = sse;

        // Watchdog: if SSE closes (server done / network drop) without firing
        // our explicit `final`/`error`/`cancel` paths, the send button would
        // stay stuck in "stop" state. Guarantee a single onEnd().
        let endCalled = false;
        const safeEnd = () => {
            if (endCalled) return;
            endCalled = true;
            onEnd();
        };

        sse.addEventListener("open", () => onStart());

        sse.addEventListener("readystatechange", (e: any) => {
            // sse.js exposes readyState: 0=connecting, 1=open, 2=closed.
            if (e?.readyState === 2) safeEnd();
        });

        sse.addEventListener("message", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                console.log("[SSE] raw event:", data);

                // --- final: stream complete ---
                if (data.final != null) {
                    onFinal(data);
                    safeEnd();
                    return;
                }

                // --- created: conversation init ---
                if (data.created != null) {
                    const mergedUser = { ...userMessage, ...data.message };
                    onCreated(
                        data.message?.conversationId || userMessage.conversationId,
                        mergedUser,
                    );
                    return;
                }

                // --- v2.5 Agent-mode SSE ---
                if (data.category != null) {
                    const { category, type, message, message_id } = data;

                    if (category === "agent_thinking" && type === "stream") {
                        const delta: string = message?.content ?? "";
                        if (!delta) return;
                        if (currentThinkingIdx == null) {
                            events.push({
                                type: "thinking",
                                content: "",
                                started_at: Date.now(),
                            });
                            currentThinkingIdx = events.length - 1;
                        }
                        const ev = events[currentThinkingIdx] as Extract<
                            AgentEvent,
                            { type: "thinking" }
                        >;
                        ev.content += delta;
                        emitLegacy();
                        emitAgent({ events: snapshot() });
                        return;
                    }

                    if (category === "agent_thinking" && type === "end") {
                        const durationMs = Number(message?.duration_ms) || 0;
                        if (currentThinkingIdx != null) {
                            const ev = events[currentThinkingIdx] as Extract<
                                AgentEvent,
                                { type: "thinking" }
                            >;
                            ev.duration_ms = durationMs;
                            ev.ended_at = Date.now();
                            currentThinkingIdx = null;
                        }
                        emitAgent({ events: snapshot() });
                        return;
                    }

                    if (category === "agent_tool_call") {
                        const tcId: string =
                            message?.tool_call_id || `tc_${events.length}`;

                        if (type === "start") {
                            // Starting a tool implicitly closes any in-flight
                            // thinking event (backend emits an explicit /end
                            // too, but belt-and-braces).
                            currentThinkingIdx = null;
                            const entry: AgentEvent = {
                                type: "tool_call",
                                tool_call_id: tcId,
                                tool_name: message?.tool_name || "",
                                display_name: message?.display_name,
                                tool_type: message?.tool_type,
                                args: message?.args,
                                inflight: true,
                                started_at: Date.now(),
                            };
                            events.push(entry);
                            toolCallIdx.set(tcId, events.length - 1);
                            responseText += `\n\n> ⏳ 正在调用工具：${entry.display_name || entry.tool_name
                                }\n\n`;
                        } else if (type === "end") {
                            const idx = toolCallIdx.get(tcId);
                            if (idx != null) {
                                const prev = events[idx] as Extract<
                                    AgentEvent,
                                    { type: "tool_call" }
                                >;
                                const endedAt = Date.now();
                                events[idx] = {
                                    ...prev,
                                    display_name:
                                        message?.display_name || prev.display_name,
                                    tool_type: message?.tool_type || prev.tool_type,
                                    args: message?.args ?? prev.args,
                                    results: message?.results,
                                    error: message?.error ?? null,
                                    inflight: false,
                                    ended_at: endedAt,
                                    duration_ms:
                                        prev.started_at != null
                                            ? endedAt - prev.started_at
                                            : prev.duration_ms,
                                };
                            }
                            const tn =
                                message?.display_name || message?.tool_name || "tool";
                            responseText += message?.error
                                ? `> ⚠️ ${tn} 失败：${message.error}\n\n`
                                : `> ✅ ${tn} 完成\n\n`;
                        }
                        emitLegacy();
                        emitAgent({ events: snapshot() });
                        return;
                    }

                    if (category === "agent_answer") {
                        if (type === "stream") {
                            const delta = message?.msg;
                            if (delta) {
                                responseText += delta;
                                const last = events[events.length - 1];
                                if (last && last.type === "text") {
                                    last.content += delta;
                                } else {
                                    events.push({ type: "text", content: delta });
                                }
                            }
                        } else if (type === "end") {
                            if (message_id) currentMessageId = String(message_id);
                            // `message.msg` on the end event is the final full
                            // string; prefer it to accumulated deltas.
                            if (typeof message?.msg === "string") {
                                responseText = message.msg;
                            }
                            // Backend may send a fresh `events` snapshot on
                            // end — trust it if present so truncation or
                            // retries can't desync.
                            if (Array.isArray(message?.events)) {
                                events.length = 0;
                                for (const ev of message.events) events.push(ev);
                            }
                            emitAgent({
                                text: responseText,
                                events: snapshot(),
                                category: "agent_answer",
                                finalised: true,
                            });
                            emitLegacy();
                            return;
                        }
                        emitLegacy();
                        emitAgent({ text: responseText, events: snapshot() });
                        return;
                    }

                    if (category === "processing" || category === "question") {
                        // Noise events — nothing to render here.
                        return;
                    }

                    console.log("[SSE] unknown category:", category);
                    return;
                }

                // --- legacy event-based delta streaming (pre-v2.5 flows) ---
                if (data.event != null) {
                    const eventType = data.event;

                    if (eventType === "on_run_step") {
                        const msgId =
                            data.data?.stepDetails?.message_creation?.message_id || "";
                        if (msgId) currentMessageId = msgId;
                        return;
                    }

                    if (eventType === "on_reasoning_delta") {
                        const deltaContent = data.data?.delta?.content;
                        if (Array.isArray(deltaContent)) {
                            for (const part of deltaContent as ContentPart[]) {
                                if (part.type === "think" && part.think) {
                                    if (currentThinkingIdx == null) {
                                        events.push({ type: "thinking", content: "" });
                                        currentThinkingIdx = events.length - 1;
                                    }
                                    const ev = events[currentThinkingIdx] as Extract<
                                        AgentEvent,
                                        { type: "thinking" }
                                    >;
                                    ev.content += part.think;
                                }
                            }
                        }
                        onMessage(
                            `:::thinking\n${thinkingText()}\n:::`,
                            currentMessageId,
                        );
                        return;
                    }

                    if (eventType === "on_message_delta") {
                        const deltaContent = data.data?.delta?.content;
                        if (Array.isArray(deltaContent)) {
                            for (const part of deltaContent as ContentPart[]) {
                                if (part.type === "text" && part.text) {
                                    responseText += part.text;
                                }
                            }
                        }
                        onMessage(legacyEnvelope(), currentMessageId);
                        return;
                    }

                    console.log("[SSE] unknown event:", eventType);
                    return;
                }

                // --- fallback: simple text streaming (legacy format) ---
                if (data.text != null || data.response != null || data.message != null) {
                    const text = data.text ?? data.response ?? "";
                    const messageId = data.messageId ?? "";
                    if (text) onMessage(text, messageId);
                }
            } catch (err) {
                console.error("[SSE] Failed to parse message:", err);
            }
        });

        sse.addEventListener("error", (e: MessageEvent) => {
            try {
                const data = JSON.parse(e.data);
                onError(data?.text || data?.message || "Stream error");
            } catch {
                onError("Connection error");
            }
            safeEnd();
        });

        sse.addEventListener("cancel", () => safeEnd());

        sse.stream();

        return () => {
            const isCancelled = sse.readyState <= 1;
            sse.close();
            if (isCancelled) sse.dispatchEvent(new Event("cancel"));
            sseRef.current = null;
        };
    }, [submission]);

    /** Abort the current SSE stream */
    const abort = () => {
        if (sseRef.current) {
            sseRef.current.close();
            sseRef.current = null;
        }
    };

    return { abort };
}
