export const KNOWLEDGE_SPACE_FILES_REFRESH_EVENT = "knowledge-space-files:refresh";
const senderId = `${Date.now()}-${Math.random()}`;

export interface KnowledgeSpaceFilesRefreshEventDetail {
    spaceId?: number | string;
}

/** Notify mounted lists and other same-origin tabs/embedded approval dialogs. */
export function dispatchKnowledgeSpaceFilesRefresh(spaceId?: number | string): void {
    const detail = { spaceId };
    window.dispatchEvent(new CustomEvent(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT, { detail }));
    try {
        const channel = new BroadcastChannel(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT);
        channel.postMessage({ ...detail, senderId });
        channel.close();
    } catch {
        // Local refresh still works when cross-context messaging is unavailable.
    }
}

export function subscribeKnowledgeSpaceFilesRefresh(
    spaceId: number | string,
    onRefresh: () => void,
): () => void {
    const receive = (detail: KnowledgeSpaceFilesRefreshEventDetail | undefined) => {
        if (detail?.spaceId != null && String(detail.spaceId) !== String(spaceId)) return;
        onRefresh();
    };
    const handleEvent = (event: Event) => receive((event as CustomEvent).detail);
    window.addEventListener(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT, handleEvent);
    let channel: BroadcastChannel | undefined;
    try {
        channel = new BroadcastChannel(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT);
        channel.onmessage = (event: MessageEvent<KnowledgeSpaceFilesRefreshEventDetail & { senderId?: string }>) => {
            if (event.data?.senderId !== senderId) receive(event.data);
        };
    } catch {
        // The local event listener does not require BroadcastChannel support.
    }
    return () => {
        window.removeEventListener(KNOWLEDGE_SPACE_FILES_REFRESH_EVENT, handleEvent);
        channel?.close();
    };
}
