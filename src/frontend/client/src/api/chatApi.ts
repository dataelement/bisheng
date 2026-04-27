/**
 * Direct API calls for the AI chat system.
 */
import http from "~/api/request";

// --- Endpoints ---
const API = {
    messages: (conversationId: string) =>
        `/api/v1/workstation/messages/${conversationId}`,
    // v2.5: native Agent-mode history (ChatResponse shape, legacy sibling
    // branches pre-collapsed server-side).
    agentMessages: (conversationId: string) =>
        `/api/v1/workstation/messages/${conversationId}/agent`,
    sseChat: () => `/api/v1/workstation/chat/completions`,
    abortChat: () => `/api/v1/workstation/chat/completions/abort`,
    deleteConversation: (id: string) => `/api/v1/chat/${id}`,
    bsConfig: () => `/api/v1/workstation/config`,
    citationDetail: (citationId: string) =>
        `/api/v1/citations/${encodeURIComponent(citationId)}`,
    citationResolve: () => `/api/v1/citations/resolve`,
};

// --- Types ---
export interface ChatCitationItem {
    itemId?: string;
    chunkId?: string;
    chunkIndex?: number;
    content?: string;
    snippet?: string;
    title?: string;
    bbox?: string | null;
    page?: number;
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
        [key: string]: any;
    };
    [key: string]: any;
}

const citationDetailMemoryCache: Record<string, ChatCitation> = {};
const citationResolveRequestCache: Record<string, Promise<ChatCitation[]>> = {};

function isRagCitationDetail(detail?: ChatCitation | null) {
    const normalizedType = detail?.type?.toLowerCase();
    return normalizedType !== "web" && normalizedType !== "websearch";
}

function hasCitationDocumentUrl(detail?: ChatCitation | null) {
    return !!detail?.sourcePayload?.downloadUrl;
}

function canUseCachedCitationDetail(detail?: ChatCitation | null) {
    return !!detail && (!isRagCitationDetail(detail) || hasCitationDocumentUrl(detail));
}

// v2.5 Agent-mode tool call shape (server emits these in agent_tool_call SSE events
// and persists an array of them inside agent_answer messages).
export type AgentToolType = "tool" | "knowledge" | "web" | string;

export interface AgentToolCall {
    tool_call_id: string;
    tool_name: string;
    display_name?: string;
    tool_type?: AgentToolType;
    args?: Record<string, any>;
    results?: any;
    error?: string | null;
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
    unfinished?: boolean;
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
    files?: any[];
    // --- v2.5 Agent-mode native fields ---
    /** One of question / agent_answer / agent_thinking / agent_tool_call / legacy answer. */
    category?: string;
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
    [key: string]: any;
}

// --- API Functions ---

/** Fetch messages for a conversation. When rendered from /share/:token the
 *  caller must pass shareToken so the backend auth middleware lets the
 *  anonymous request through. */
export async function getMessages(
    conversationId: string,
    shareToken?: string
): Promise<ChatMessage[]> {
    if (!conversationId || conversationId === "new") {
        return [];
    }
    const headers = shareToken ? { 'share-token': shareToken } : undefined;
    const res = await http.get(API.messages(conversationId), headers ? { headers } : undefined);
    return res?.data ?? res ?? [];
}

/**
 * v2.5: Fetch messages in native Agent-mode shape (ChatResponse).
 * - Legacy regenerate sibling branches are pre-collapsed server-side.
 * - Each row already has `category`, and agent_answer rows come with the
 *   structured JSON payload split into `message` { msg, reasoning_content,
 *   tool_calls[], steps[] } on the response.
 *
 * Response items look like:
 *   { message_id, category, type, message: {...}, is_bot, chat_id, ... }
 *
 * Mapped to ChatMessage here so the renderer doesn't have to branch on the
 * server shape.
 */
export async function getAgentMessages(
    conversationId: string
): Promise<ChatMessage[]> {
    if (!conversationId || conversationId === "new") {
        return [];
    }
    const res = await http.get(API.agentMessages(conversationId));
    const rows: any[] = res?.data ?? res ?? [];
    return rows.map(mapAgentResponseItem);
}

function mapAgentResponseItem(row: any): ChatMessage {
    const category: string = row.category;
    const raw = row.message;
    const base: ChatMessage = {
        messageId: String(row.message_id ?? ""),
        parentMessageId: "",
        conversationId: row.chat_id ?? "",
        sender: row.is_bot ? "assistant" : "user",
        text: "",
        isCreatedByUser: !row.is_bot,
        createdAt: row.create_time,
        category,
        files: Array.isArray(row.files) ? row.files : [],
        citations: Array.isArray(row.citations) ? row.citations : null,
    };

    if (category === "question" && raw && typeof raw === "object") {
        base.text = raw.query ?? "";
        return base;
    }

    if (category === "agent_answer" && raw && typeof raw === "object") {
        base.text = raw.msg ?? "";
        // Backend always normalises agent_answer rows to {msg, events}, even
        // for older DB shapes (`chat_helpers._normalise_agent_message_content`).
        base.events = Array.isArray(raw.events) ? (raw.events as AgentEvent[]) : [];
        return base;
    }

    // Fallback — unknown categories land as plain text.
    base.text = typeof raw === "string" ? raw : JSON.stringify(raw ?? "");
    return base;
}

/** Abort an active SSE stream */
export async function abortChat(abortKey: string): Promise<void> {
    await http.post(API.abortChat(), {
        abortKey,
        endpoint: "custom",
    });
}

/** Delete a conversation */
export async function deleteConversation(
    conversationId: string
): Promise<void> {
    await http.delete(API.deleteConversation(conversationId));
}

export async function getCitationDetail(citationId: string): Promise<ChatCitation> {
    if (canUseCachedCitationDetail(citationDetailMemoryCache[citationId])) {
        return citationDetailMemoryCache[citationId];
    }

    const res = await http.get<any>(API.citationDetail(citationId));
    const detail = res?.data ?? res;
    if (detail?.citationId) {
        citationDetailMemoryCache[detail.citationId] = detail;
    }
    citationDetailMemoryCache[citationId] = detail;
    return detail;
}

export async function resolveCitationDetails(citationIds: string[]): Promise<ChatCitation[]> {
    const uniqueCitationIds = Array.from(new Set(
        citationIds.filter((citationId) => citationId && !citationId.startsWith("citation:")),
    )).filter((citationId) => !canUseCachedCitationDetail(citationDetailMemoryCache[citationId]));

    if (!uniqueCitationIds.length) {
        return citationIds
            .map((citationId) => citationDetailMemoryCache[citationId])
            .filter(Boolean);
    }

    const requestKey = uniqueCitationIds.slice().sort().join("|");
    if (!citationResolveRequestCache[requestKey]) {
        citationResolveRequestCache[requestKey] = http.post(API.citationResolve(), {
            citationIds: uniqueCitationIds,
        }).then((res) => {
            const payload = res?.data ?? res;
            const items = Array.isArray(payload?.items)
                ? payload.items
                : Array.isArray(payload)
                    ? payload
                    : [];
            items.forEach((detail) => {
                if (detail?.citationId) {
                    citationDetailMemoryCache[detail.citationId] = detail;
                }
            });
            return items;
        }).finally(() => {
            delete citationResolveRequestCache[requestKey];
        });
    }

    const resolvedItems = await citationResolveRequestCache[requestKey];
    return citationIds
        .map((citationId) => citationDetailMemoryCache[citationId])
        .filter(Boolean)
        .concat(resolvedItems.filter((detail) => detail?.citationId && !citationIds.includes(detail.citationId)));
}

/** Get the full SSE URL (absolute) for creating SSE connection */
export function getSSEUrl(): string {
    const base = import.meta.env.BASE_URL?.replace(/\/$/, "") || "";
    return `${base}${API.sseChat()}`;
}

/** Get the full SSE URL for channel article chat */
export function getChannelSSEUrl(): string {
    const base = import.meta.env.BASE_URL?.replace(/\/$/, "") || "";
    return `${base}/api/v1/channel/chat/completions`;
}

/** Fetch platform config (models, features, etc.) */
export async function getBsConfig(): Promise<BsConfig> {
    const res = await http.get(API.bsConfig());
    return res?.data ?? res;
}

/** Build a message tree from a flat message array */
export function buildMessageTree(messages: ChatMessage[]): ChatMessage[] {
    if (!messages || messages.length === 0) return [];

    const map: Record<string, ChatMessage & { children: ChatMessage[] }> = {};
    const roots: ChatMessage[] = [];
    const childrenCount: Record<string, number> = {};

    messages.forEach((msg) => {
        const parentId = msg.parentMessageId ?? "";
        childrenCount[parentId] = (childrenCount[parentId] || 0) + 1;

        const extended = {
            ...msg,
            children: [],
            depth: 0,
            siblingIndex: childrenCount[parentId] - 1,
        };
        map[msg.messageId] = extended;

        const parent = map[parentId];
        if (parent) {
            parent.children.push(extended);
            extended.depth = parent.depth! + 1;
        } else {
            roots.push(extended);
        }
    });

    return roots;
}

// --- Channel Article Chat API Functions ---

/** Fetch channel article chat history (returns ChatMessage-compatible objects) */
export async function getChannelChatHistory(
    articleDocId: string
): Promise<ChatMessage[]> {
    if (!articleDocId) return [];
    const res = await http.get(`/api/v1/channel/chat/messages/${articleDocId}`);
    const items: StreamHistoryItem[] = res?.data ?? [];
    // Channel API returns oldest-first, no need to reverse
    return items.map(parseStreamHistoryItem);
}

/** Clear channel article chat history */
export async function clearChannelChat(articleDocId: string): Promise<void> {
    await http.delete(`/api/v1/channel/chat/messages/${articleDocId}`);
}

// =====================================================================
// Shared Stream-Format Types & Parser
// (Used by channel, file, and folder chat — the "new" data structure)
// =====================================================================

/** Raw history item from stream-format endpoints (file/folder/channel) */
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
    [key: string]: any;
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

    return {
        messageId: String(raw.id),
        parentMessageId: "",
        conversationId: raw.chat_id || "",
        sender: raw.is_bot ? "AI" : "User",
        text: displayText,
        isCreatedByUser: !raw.is_bot,
        createdAt: raw.create_time,
        error: false,
        flow_name: raw.flow_name,
    };
}

// =====================================================================
// Knowledge Space — Single File Chat
// =====================================================================

/** Get the full SSE URL for single-file chat */
export function getFileChatSSEUrl(
    spaceId: string | number,
    fileId: string | number
): string {
    const base = import.meta.env.BASE_URL?.replace(/\/$/, "") || "";
    return `${base}/api/v1/knowledge/space/${spaceId}/chat/file/${fileId}`;
}

/** Fetch single-file chat history (POST endpoint) */
export async function getFileChatHistory(
    spaceId: string | number,
    fileId: string | number
): Promise<ChatMessage[]> {
    if (!spaceId || !fileId) return [];
    const res = await http.get(
        `/api/v1/knowledge/space/${spaceId}/chat/file/${fileId}/history`
    );
    const items: StreamHistoryItem[] = res?.data ?? [];
    // Backend returns newest-first; reverse for chronological order
    return items.reverse().map(parseStreamHistoryItem);
}

/** Delete single-file chat history */
export async function clearFileChatHistory(
    spaceId: string | number,
    fileId: string | number
): Promise<void> {
    await http.delete(
        `/api/v1/knowledge/space/${spaceId}/chat/file/${fileId}/history`
    );
}

// =====================================================================
// Knowledge Space — Folder / Space Chat
// =====================================================================

/** Folder session record returned by the sessions API */
export interface FolderSession {
    chat_id: string;
    flow_id: string;
    flow_name: string;
    /** User-visible title; may be empty until renamed or title generation */
    name?: string | null;
    create_time: string;
    update_time: string;
    [key: string]: any;
}

/** Get the SSE URL for folder/space chat */
export function getFolderChatSSEUrl(spaceId: string | number): string {
    const base = import.meta.env.BASE_URL?.replace(/\/$/, "") || "";
    return `${base}/api/v1/knowledge/space/${spaceId}/chat/folder`;
}

/** Fetch folder/space session list */
export async function getFolderSessions(
    spaceId: string | number,
    folderId?: string | number
): Promise<FolderSession[]> {
    const params: Record<string, any> = {};
    if (folderId != null && folderId !== "") params.folder_id = folderId;
    const res = await http.get(
        `/api/v1/knowledge/space/${spaceId}/chat/folder/session`,
        { params }
    );
    return res?.data ?? [];
}

/** Create a new folder/space chat session, returns session data (contains chat_id) */
export async function createFolderSession(
    spaceId: string | number,
    folderId?: number
): Promise<FolderSession> {
    const body: Record<string, any> = {};
    if (folderId != null) body.folder_id = folderId;
    const res = await http.post(
        `/api/v1/knowledge/space/${spaceId}/chat/folder/session`,
        body
    );
    return res?.data;
}

/** Delete a folder/space chat session */
export async function deleteFolderSession(
    spaceId: string | number,
    chatId: string,
    folderId?: number
): Promise<void> {
    const body: Record<string, any> = { chat_id: chatId };
    if (folderId != null) body.folder_id = folderId;
    await http.deleteWithOptions(
        `/api/v1/knowledge/space/${spaceId}/chat/folder/session`,
        { data: body }
    );
}

/** Rename a chat session (POST /api/v1/chat/conversation/rename) */
export async function renameConversation(
    chatId: string,
    name: string
): Promise<void> {
    await http.post(`/api/v1/chat/conversation/rename`, {
        conversationId: chatId,
        name: name.trim(),
    });
}

/** Fetch folder/space chat history for a specific session */
export async function getFolderChatHistory(
    spaceId: string | number,
    params: {
        folderId?: string | number;
        chatId?: string;
        pageSize?: number;
    }
): Promise<ChatMessage[]> {
    const queryParams: Record<string, any> = {};
    if (params.folderId != null && params.folderId !== "")
        queryParams.folder_id = params.folderId;
    if (params.chatId) queryParams.chat_id = params.chatId;
    if (params.pageSize) queryParams.page_size = params.pageSize;

    const res = await http.get(
        `/api/v1/knowledge/space/${spaceId}/chat/folder/history`,
        { params: queryParams }
    );
    const items: StreamHistoryItem[] = res?.data ?? [];
    // Backend returns newest-first; reverse for chronological order
    return items.reverse().map(parseStreamHistoryItem);
}
