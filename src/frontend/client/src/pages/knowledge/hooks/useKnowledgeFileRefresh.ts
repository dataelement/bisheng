import { useEffect, useRef } from "react";
import { subscribeKnowledgeSpaceFilesRefresh } from "../knowledgeFileRefresh";

/** Keep refresh notifications independent of the current search/folder closure. */
export function useKnowledgeFileRefresh(
    spaceId: number | string | undefined,
    onRefresh: () => unknown | Promise<unknown>,
    hasPendingPublishApproval = false,
    onPoll = onRefresh,
) {
    const refreshRef = useRef(onRefresh);
    refreshRef.current = onRefresh;
    const pollRef = useRef(onPoll);
    pollRef.current = onPoll;

    useEffect(() => {
        if (spaceId == null) return;
        let disposed = false;
        let running = false;
        let requested = false;
        let fullRefreshRequested = false;
        const refresh = async (poll = false) => {
            requested = true;
            fullRefreshRequested ||= !poll;
            if (running) return;
            running = true;
            try {
                while (requested && !disposed) {
                    requested = false;
                    const callback = fullRefreshRequested ? refreshRef.current : pollRef.current;
                    fullRefreshRequested = false;
                    await callback();
                }
            } catch {
                // Keep the current rows after a background refresh failure.
            } finally {
                running = false;
            }
        };
        const unsubscribe = subscribeKnowledgeSpaceFilesRefresh(spaceId, () => { void refresh(); });
        const handleFocus = () => { void refresh(); };
        window.addEventListener("focus", handleFocus);
        const timer = hasPendingPublishApproval
            ? window.setInterval(() => { if (!document.hidden) void refresh(true); }, 5000)
            : undefined;
        return () => {
            disposed = true;
            unsubscribe();
            window.removeEventListener("focus", handleFocus);
            if (timer !== undefined) window.clearInterval(timer);
        };
    }, [spaceId, hasPendingPublishApproval]);
}
