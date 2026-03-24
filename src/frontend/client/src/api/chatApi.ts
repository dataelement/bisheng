/**
 * Direct API calls for the AI chat system.
 */
import axios from "axios";

const http = axios.create({
    baseURL: import.meta.env.BASE_URL,
});

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
    return res.data?.data ?? res.data ?? [];
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
    return res.data?.data ?? res.data;
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
    return res.data?.data ?? res.data ?? [];
}

/** Clear channel article chat history */
export async function clearChannelChat(articleDocId: string): Promise<void> {
    await http.delete(`/api/v1/channel/chat/messages/${articleDocId}`);
}

