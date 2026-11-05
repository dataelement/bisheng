import { useCallback, useState } from "react";
import type { ChatMessage } from "~/api/chatApi";
const EMPTY_MESSAGES: ChatMessage[] = [];

export function useChatBuckets(initialConversationId: string) {
    // --- Local state ---
    // Bucketed by conversation: switching only changes which bucket renders, so
    // a turn the user walked away from keeps writing into its own.
    const [messagesByConvo, setMessagesByConvo] = useState<Record<string, ChatMessage[]>>({});
    const [titleByConvo, setTitleByConvo] = useState<Record<string, string>>({});
    const [streamingByConvo, setStreamingByConvo] = useState<Record<string, boolean>>({});
    const [loadingByConvo, setLoadingByConvo] = useState<Record<string, boolean>>({});
    const [parsingMediaByConvo, setParsingMediaByConvo] = useState<Record<string, boolean>>({});
    const [conversationId, setConversationId] = useState(initialConversationId);

    // What the caller sees: the active conversation's slice of the above.
    const messages = messagesByConvo[conversationId] ?? EMPTY_MESSAGES;
    const title = titleByConvo[conversationId] ?? "";
    const isStreaming = !!streamingByConvo[conversationId];
    const isLoading = !!loadingByConvo[conversationId];
    const isParsingMedia = !!parsingMediaByConvo[conversationId];

    // Every write names the conversation it targets, because a turn's callbacks
    // may well fire while the user is reading a different chat.
    const setMessagesFor = useCallback(
        (cid: string, updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) => {
            setMessagesByConvo((prev) => {
                const cur = prev[cid] ?? EMPTY_MESSAGES;
                const next = typeof updater === "function" ? updater(cur) : updater;
                return next === cur ? prev : { ...prev, [cid]: next };
            });
        },
        [],
    );
    const setTitleFor = useCallback(
        (cid: string, updater: string | ((prev: string) => string)) => {
            setTitleByConvo((prev) => {
                const cur = prev[cid] ?? "";
                const next = typeof updater === "function" ? updater(cur) : updater;
                return next === cur ? prev : { ...prev, [cid]: next };
            });
        },
        [],
    );
    const setStreamingFor = useCallback((cid: string, value: boolean) => {
        setStreamingByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);
    const setLoadingFor = useCallback((cid: string, value: boolean) => {
        setLoadingByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);
    const setParsingMediaFor = useCallback((cid: string, value: boolean) => {
        setParsingMediaByConvo((prev) => (!!prev[cid] === value ? prev : { ...prev, [cid]: value }));
    }, []);

    /** Move a turn's buckets when it learns its real conversation id, so the
     *  answer the user is watching is still there once the URL catches up. */
    const promoteBucket = useCallback((from: string, to: string) => {
        if (!to || to === from) return;
        const move = <T,>(prev: Record<string, T>): Record<string, T> => {
            if (!(from in prev)) return prev;
            const { [from]: carried, ...rest } = prev;
            return { ...rest, [to]: carried };
        };
        setMessagesByConvo(move);
        setTitleByConvo(move);
        setStreamingByConvo(move);
        setLoadingByConvo(move);
        setParsingMediaByConvo(move);
    }, []);

    // The viewed conversation's writers, for everything outside a turn (loading
    // history, clearing, the switch effect).
    const setMessages = useCallback(
        (updater: ChatMessage[] | ((prev: ChatMessage[]) => ChatMessage[])) =>
            setMessagesFor(conversationId, updater),
        [conversationId, setMessagesFor],
    );
    const setTitle = useCallback(
        (updater: string | ((prev: string) => string)) => setTitleFor(conversationId, updater),
        [conversationId, setTitleFor],
    );
    const setIsStreaming = useCallback(
        (value: boolean) => setStreamingFor(conversationId, value),
        [conversationId, setStreamingFor],
    );
    const setIsLoading = useCallback(
        (value: boolean) => setLoadingFor(conversationId, value),
        [conversationId, setLoadingFor],
    );
    const setIsParsingMedia = useCallback(
        (value: boolean) => setParsingMediaFor(conversationId, value),
        [conversationId, setParsingMediaFor],
    );

    return { messages, title, isStreaming, isLoading, isParsingMedia, conversationId, streamingByConvo, setConversationId, setMessagesFor, setTitleFor, setStreamingFor, setLoadingFor, setParsingMediaFor, promoteBucket, setMessages, setTitle, setIsStreaming, setIsLoading, setIsParsingMedia };
}
