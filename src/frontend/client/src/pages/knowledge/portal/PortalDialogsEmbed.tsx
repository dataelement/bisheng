import { useEffect, useRef } from "react";
import { ApprovalCenterDialog } from "~/components/approval/ApprovalCenterDialog";
import { NotificationsDialog } from "~/components/NotificationsDialog";
import { usePortalApprovalBridge } from "./hooks/usePortalApprovalBridge";

/**
 * Standalone, chrome-less host for the approval-center and notifications
 * dialogs. The portal embeds this route in a hidden, full-viewport iframe and
 * drives it via postMessage (see usePortalApprovalBridge), so the dialogs can
 * be opened from ANY portal page instead of only inside the knowledge
 * workbench. The page body is transparent; only the dialog (with its own dim
 * backdrop) is visible.
 *
 * We tell the parent to hide the overlay only on the transition from
 * "some dialog open" -> "all closed". This must be derived from the settled
 * state (via effect), NOT from an onOpenChange closure: the notifications
 * "查看审批" button closes notifications AND opens the approval dialog in the
 * same tick, and a stale-closure check would wrongly see "all closed" and hide
 * the overlay mid-handoff, leaving the approval dialog open but invisible.
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

  // Notify the parent to hide the overlay only when every dialog has closed,
  // and only after at least one was open (so we never post on initial mount).
  const anyOpen = approvalDialogOpen || notificationsOpen;
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (wasOpenRef.current && !anyOpen) {
      window.parent?.postMessage({ type: DIALOG_CLOSED_MESSAGE }, "*");
    }
    wasOpenRef.current = anyOpen;
  }, [anyOpen]);

  return (
    <>
      <NotificationsDialog
        open={notificationsOpen}
        onOpenChange={setNotificationsOpen}
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
        onOpenChange={setApprovalDialogOpen}
        target={approvalDialogTarget}
      />
    </>
  );
}
