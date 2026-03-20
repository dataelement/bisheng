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

        // 定时刷新未读数量（每30秒）
        const interval = setInterval(fetchUnreadCount, 30000);

        return () => clearInterval(interval);
    }, []);

    return { unreadCount, refreshCount: fetchUnreadCount };
}
