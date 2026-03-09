/**
 * useKnowledgeAiSession — manages per-location conversation session memory.
 * Uses localStorage for persistence (future API migration ready).
 * 
 * Key format: "kb-ai-session-{locationKey}" for active conversation
 * Key format: "kb-ai-history-{locationKey}" for conversation list
 */
import { useCallback, useMemo, useState } from "react";

interface ConversationRecord {
    id: string;
    title: string;
    createdAt: string;
    updatedAt: string;
}

interface UseKnowledgeAiSessionReturn {
    /** Current active conversation ID */
    conversationId: string;
    /** Set active conversation ID and persist */
    setConversationId: (id: string) => void;
    /** Clear active session (reset to welcome) */
    clearSession: () => void;
    /** List of conversation records for this location */
    history: ConversationRecord[];
    /** Add a conversation record to history */
    addToHistory: (record: ConversationRecord) => void;
    /** Load a specific conversation from history */
    loadConversation: (id: string) => void;
}

export function useKnowledgeAiSession(locationKey: string): UseKnowledgeAiSessionReturn {
    const sessionKey = `kb-ai-session-${locationKey}`;
    const historyKey = `kb-ai-history-${locationKey}`;

    const [conversationId, setConversationIdState] = useState<string>(() => {
        return localStorage.getItem(sessionKey) || "new";
    });

    const [history, setHistory] = useState<ConversationRecord[]>(() => {
        try {
            const saved = localStorage.getItem(historyKey);
            return saved ? JSON.parse(saved) : [];
        } catch {
            return [];
        }
    });

    const setConversationId = useCallback((id: string) => {
        setConversationIdState(id);
        localStorage.setItem(sessionKey, id);
    }, [sessionKey]);

    const clearSession = useCallback(() => {
        setConversationIdState("new");
        localStorage.removeItem(sessionKey);
    }, [sessionKey]);

    const addToHistory = useCallback((record: ConversationRecord) => {
        setHistory(prev => {
            // Avoid duplicates, update existing
            const existing = prev.findIndex(r => r.id === record.id);
            let updated: ConversationRecord[];
            if (existing >= 0) {
                updated = [...prev];
                updated[existing] = record;
            } else {
                updated = [record, ...prev];
            }
            localStorage.setItem(historyKey, JSON.stringify(updated));
            return updated;
        });
    }, [historyKey]);

    const loadConversation = useCallback((id: string) => {
        setConversationId(id);
    }, [setConversationId]);

    return {
        conversationId,
        setConversationId,
        clearSession,
        history,
        addToHistory,
        loadConversation,
    };
}
