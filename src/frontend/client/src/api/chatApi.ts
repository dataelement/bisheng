/**
 * Direct API calls for the AI chat system.
 */
import http from "~/api/request";

// --- Endpoints ---
const API = {
    messages: (conversationId: string) =>
        `/api/v1/workstation/messages/${conversationId}`,
    sseChat: () => `/api/v1/workstation/chat/completions`,
    abortChat: () => `/api/v1/workstation/chat/completions/abort`,
    deleteConversation: (id: string) => `/api/v1/chat/${id}`,
    bsConfig: () => `/api/v1/workstation/config`,
};

// --- Types ---
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
    files?: any[];
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

/** Fetch messages for a conversation */
export async function getMessages(
    conversationId: string
): Promise<ChatMessage[]> {
    if (!conversationId || conversationId === "new") {
        return [];
    }
    const res = await http.get(API.messages(conversationId));
    return res?.data ?? res ?? [];
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

