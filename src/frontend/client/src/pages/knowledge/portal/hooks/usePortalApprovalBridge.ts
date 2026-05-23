import { useEffect, useState } from "react";
import type { ApprovalCenterTab } from "~/api/approval";

type ApprovalDialogTarget = {
    tab?: ApprovalCenterTab;
    instanceId?: number;
    taskId?: number;
};

export function usePortalApprovalBridge() {
    const [approvalDialogOpen, setApprovalDialogOpen] = useState(false);
    const [approvalDialogTarget, setApprovalDialogTarget] = useState<ApprovalDialogTarget>({
        tab: "my_tasks",
    });
    const [notificationsOpen, setNotificationsOpen] = useState(false);

    useEffect(() => {
        const openApprovalCenter = (tab: ApprovalCenterTab) => {
            setApprovalDialogTarget({ tab });
            setApprovalDialogOpen(true);
            setNotificationsOpen(false);
        };

        const handlePortalMessage = (event: MessageEvent) => {
            const type = event.data?.type;
            if (type === "shougang-portal:open-approval-tasks") {
                openApprovalCenter("my_tasks");
            } else if (type === "shougang-portal:open-approval-requests") {
                openApprovalCenter("my_requests");
            } else if (type === "shougang-portal:open-notifications") {
                setNotificationsOpen(true);
                setApprovalDialogOpen(false);
            }
        };

        window.addEventListener("message", handlePortalMessage);
        return () => window.removeEventListener("message", handlePortalMessage);
    }, []);

    return {
        approvalDialogOpen,
        approvalDialogTarget,
        notificationsOpen,
        setApprovalDialogOpen,
        setApprovalDialogTarget,
        setNotificationsOpen,
    };
}
