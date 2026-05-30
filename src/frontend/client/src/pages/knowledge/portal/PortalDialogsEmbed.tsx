import { useEffect } from "react";
import { ApprovalCenterDialog } from "~/components/approval/ApprovalCenterDialog";
import { NotificationsDialog } from "~/components/NotificationsDialog";
import { usePortalApprovalBridge } from "./hooks/usePortalApprovalBridge";

/**
 * Standalone, chrome-less host for the approval-center and notifications
 * dialogs. The portal embeds this route in a hidden, full-viewport iframe and
 * drives it via postMessage (see usePortalApprovalBridge), so the dialogs can
 * be opened from ANY portal page instead of only inside the knowledge
 * workbench. The page body is transparent; only the dialog (with its own dim
 * backdrop) is visible. When both dialogs close, we notify the parent so it can
 * hide the overlay iframe.
 */
const DIALOG_CLOSED_MESSAGE = "shougang-portal:dialog-closed";

export default function PortalDialogsEmbed() {
  const {
    approvalDialogOpen,
    approvalDialogTarget,
    notificationsOpen,
    setApprovalDialogOpen,
    setApprovalDialogTarget,
    setNotificationsOpen,
  } = usePortalApprovalBridge();

  // Keep the iframe document transparent so nothing shows when idle.
  useEffect(() => {
    const previous = document.body.style.background;
    document.body.style.background = "transparent";
    return () => {
      document.body.style.background = previous;
    };
  }, []);

  const notifyParentIfAllClosed = (nextApprovalOpen: boolean, nextNotificationsOpen: boolean) => {
    if (!nextApprovalOpen && !nextNotificationsOpen) {
      window.parent?.postMessage({ type: DIALOG_CLOSED_MESSAGE }, "*");
    }
  };

  return (
    <>
      <NotificationsDialog
        open={notificationsOpen}
        onOpenChange={(open) => {
          setNotificationsOpen(open);
          notifyParentIfAllClosed(approvalDialogOpen, open);
        }}
        onOpenApprovalCenter={(target) => {
          setNotificationsOpen(false);
          setApprovalDialogTarget({
            tab: target.tab,
            instanceId: target.instanceId ?? undefined,
            taskId: target.taskId ?? undefined,
          });
          setApprovalDialogOpen(true);
        }}
      />

      <ApprovalCenterDialog
        open={approvalDialogOpen}
        onOpenChange={(open) => {
          setApprovalDialogOpen(open);
          notifyParentIfAllClosed(open, notificationsOpen);
        }}
        target={approvalDialogTarget}
      />
    </>
  );
}
