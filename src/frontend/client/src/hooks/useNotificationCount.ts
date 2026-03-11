import { useState, useEffect } from "react";
import { getNotificationsApi } from "~/api/notifications";
import { getMockNotifications } from "~/mock/notifications";

export function useNotificationCount() {
    const [unreadCount, setUnreadCount] = useState(0);

    const fetchUnreadCount = async () => {
        try {
            // 使用模拟数据
            const response = getMockNotifications({
                onlyUnread: true
            });
            setUnreadCount(response.unreadCount || 0);
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
