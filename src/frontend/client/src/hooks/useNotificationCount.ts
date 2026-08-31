import { useCallback, useEffect, useState } from "react";
import { getMyPendingApprovalCountApi } from "~/api/approval";
import { getMessageUnreadCountApi } from "~/api/message";

const REFRESH_INTERVAL_MS = 150000;

/**
 * Badge counts for the 消息与审批 entry.
 *
 * The two numbers stay separate on purpose: "还有几件事要办" (pending approval tasks) and
 * "还有几条没看" (unread notifications) mean different things, so they are never summed into
 * one ambiguous total. The entry shows the pending count as a number and falls back to a plain
 * dot when there is nothing to handle but something unread.
 */
export function useNotificationCount() {
    const [unreadCount, setUnreadCount] = useState(0);
    const [pendingApprovalCount, setPendingApprovalCount] = useState(0);

    const fetchCounts = useCallback(async () => {
        const [unread, pending] = await Promise.allSettled([
            getMessageUnreadCountApi(),
            getMyPendingApprovalCountApi(),
        ]);
        if (unread.status === "fulfilled") {
            // `notify` already excludes approval to-dos, which live in 我的审批 instead.
            setUnreadCount(unread.value.notify || 0);
        } else {
            console.error("Failed to fetch unread count:", unread.reason);
        }
        if (pending.status === "fulfilled") {
            setPendingApprovalCount(pending.value || 0);
        } else {
            console.error("Failed to fetch pending approval count:", pending.reason);
        }
    }, []);

    useEffect(() => {
        void fetchCounts();

        const interval = setInterval(() => {
            void fetchCounts();
        }, REFRESH_INTERVAL_MS);

        // Refresh as soon as the tab is looked at again, so the badge is never stale on return.
        const onFocus = () => {
            void fetchCounts();
        };
        const onVisibilityChange = () => {
            if (document.visibilityState === "visible") {
                void fetchCounts();
            }
        };
        window.addEventListener("focus", onFocus);
        document.addEventListener("visibilitychange", onVisibilityChange);

        return () => {
            clearInterval(interval);
            window.removeEventListener("focus", onFocus);
            document.removeEventListener("visibilitychange", onVisibilityChange);
        };
    }, [fetchCounts]);

    return { unreadCount, pendingApprovalCount, refreshCount: fetchCounts };
}
