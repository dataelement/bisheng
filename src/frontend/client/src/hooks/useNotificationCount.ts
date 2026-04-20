import { useState, useEffect } from "react";
import { getMessageUnreadCountApi } from "~/api/message";

export function useNotificationCount() {
    const [unreadCount, setUnreadCount] = useState(0);

    const fetchUnreadCount = async () => {
        try {
            const { total } = await getMessageUnreadCountApi();
            setUnreadCount(total || 0);
        } catch (error) {
            console.error("Failed to fetch unread count:", error);
        }
    };

    useEffect(() => {
        fetchUnreadCount();

        // 定时刷新未读数量
        const interval = setInterval(fetchUnreadCount, 150000);

        // 页面重新可见/聚焦时立即刷新，避免红点延迟
        const onFocus = () => { void fetchUnreadCount(); };
        const onVisibilityChange = () => {
            if (document.visibilityState === "visible") {
                void fetchUnreadCount();
            }
        };
        window.addEventListener("focus", onFocus);
        document.addEventListener("visibilitychange", onVisibilityChange);

        return () => {
            clearInterval(interval);
            window.removeEventListener("focus", onFocus);
            document.removeEventListener("visibilitychange", onVisibilityChange);
        };
    }, []);

    return { unreadCount, refreshCount: fetchUnreadCount };
}
