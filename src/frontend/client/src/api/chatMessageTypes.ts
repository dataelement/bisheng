import type { FailureInfo } from '~/utils/failureInfo';

export interface ChatCitationItem {
    itemId?: string;
    chunkId?: string;
    chunkIndex?: number;
    content?: string;
    snippet?: string;
    title?: string;
    bbox?: string | null;
    page?: number;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    [key: string]: any;
}

export interface ChatCitation {
    citationId: string;
    type: string;
    itemId?: string | null;
    sourcePayload?: {
        url?: string;
        title?: string;
        snippet?: string;
        source?: string;
        sourceUrl?: string;
        previewUrl?: string;
        downloadUrl?: string;
        knowledgeName?: string;
        documentName?: string;
        items?: ChatCitationItem[];
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
        [key: string]: any;
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    [key: string]: any;
}

export type AgentToolType = "tool" | "knowledge" | "web" | string;

export interface AgentToolCall {
    tool_call_id: string;
    tool_name: string;
    display_name?: string;
    tool_type?: AgentToolType;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    args?: Record<string, any>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    results?: any;
    error?: string | null;
    failure_info?: FailureInfo;
    /** True while the backend is still running this tool (no `end` event seen yet). */
    inflight?: boolean;
    /** Epoch ms when the start event arrived; lets the UI compute a live duration. */
    started_at?: number;
    /** Epoch ms when the end event arrived. Used for wall-clock group span on reload. */
    ended_at?: number;
    /** Final duration; backend or frontend may stamp it. */
    duration_ms?: number;
}

// Unified ordered event — one per thinking segment or tool call in arrival order.
// Replaces the old parallel arrays (thinking_segments + tool_calls +
// after_segment/segment_idx cross-references).
export type AgentEvent =
    | {
          type: "thinking";
          content: string;
          /** Epoch ms when the first delta arrived. */
          started_at?: number;
          /** Epoch ms when the `agent_thinking/end` event arrived. */
          ended_at?: number;
          /** Final duration; absent while the segment is still streaming. */
          duration_ms?: number;
      }
    | ({ type: "tool_call" } & AgentToolCall)
    | {
          type: "text";
          content: string;
      };

export interface ChatMessage {
    messageId: string;
    parentMessageId: string;
    conversationId: string;
    sender: "user" | "assistant" | string;
    text: string;
    clientTimestamp?: string;
    content?: ContentPart[];
    error?: boolean;
    /** backend status_code on an errored assistant row — lets the UI show the calm
        ServiceBusyNotice + Retry for transient codes (rate limit / busy) vs the red
        error bubble for terminal ones. */
    errorCode?: number;
    /** stable failure classification from the backend (`data.error_type` on the SSE
        error envelope) — picks the card's title/explanation/hint copy. */
    errorType?: string;
    /** raw upstream text (provider message, parser error, offending filename) kept
        behind the card's "view details" disclosure. */
    errorDetail?: string;
    failureInfo?: FailureInfo;
    /** Human-readable failure copy for an errored assistant row. Kept apart from
        `text` so a stream that failed *after* emitting an answer keeps that answer
        renderable — overwriting `text` would destroy it. */
    errorText?: string;
    /** Set by streaming text callbacks, separate from legacy diagnostic text. */
    hasAnswerContent?: boolean;
    unfinished?: boolean;
    /** Stable server-owned identity for all attempts of one logical answer. */
    executionId?: string;
    /** Active attempt accepted by the server; stale stream events are ignored. */
    attemptId?: string;
    /** Existing question record used to reconstruct a user-triggered recovery. */
    recoverySubjectId?: string;
    modelId?: string | number;
    rateLimitState?: "recovering" | "busy" | "normal";
    resumeMode?: string;
    isCreatedByUser?: boolean;
    createdAt?: string;
    children?: ChatMessage[];
    depth?: number;
    siblingIndex?: number;
    flow_name?: string;
    // Web search results
    searchResult?: SearchWebItem[];
    // Reference sources
    references?: ReferenceSource[];
    citations?: ChatCitation[] | null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    files?: any[];
    /** Persisted like/dislike verdict on this answer row: 0 none / 1 up / 2 down.
        Seeds the feedback buttons' highlight on history reload. */
    liked?: number;
    // --- v2.5 Agent-mode native fields ---
    /** One of question / agent_answer / agent_thinking / agent_tool_call / task / legacy answer. */
    category?: string;
    /**
     * F035 Track J: for `category==='task'` bot rows, points at the linsight
     * session_version holding the execution detail (tasks/sop/steps/files). The
     * inline task bubble lazy-loads the rich panel by this id.
     */
    linsightSessionVersionId?: string;
    /**
     * Ordered log of thinking segments + tool calls, in arrival order.
     * This is the primary source for agent-native rendering. Historical
     * rows written before this field existed are reconstructed from their
     * legacy fields in `mapAgentResponseItem`.
     */
    events?: AgentEvent[];
}

export interface ContentPart {
    type: string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    [key: string]: any;
}

export interface SearchWebItem {
    url: string;
    title: string;
    snippet: string;
}

export interface ReferenceSource {
    title: string;
    url?: string;
    content?: string;
}

export interface BsConfig {
    models: Array<{
        key: string;
        id: string;
        name: string;
        displayName: string;
    }>;
    voiceInput: { enabled: boolean; model: string };
    webSearch: { enabled: boolean };
    knowledgeBase: { enabled: boolean; prompt: string };
    fileUpload: { enabled: boolean; prompt: string };
    inputPlaceholder?: string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Preserve the existing chat payload contract during extraction.
    [key: string]: any;
}
