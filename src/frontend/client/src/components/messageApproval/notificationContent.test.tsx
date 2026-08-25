import type { MessageItem } from "~/api/message";
import {
  APPROVAL_CENTER_ACTION_CODES,
  isApprovalCenterNotification,
  resolveApprovalCenterTarget,
} from "./notificationContent";

describe("resource user invite notification routing", () => {
  const pendingInvite: MessageItem = {
    id: 1,
    sender: 7,
    sender_name: "Inviter",
    receiver: [9],
    message_type: "notify",
    action_code: "resource_user_invite_pending",
    status: "approved",
    is_read: false,
    create_time: "2026-08-10T00:00:00Z",
    update_time: "2026-08-10T00:00:00Z",
    content: [
      { type: "system_text", content: "resource_user_invite_pending" },
      {
        type: "business_url",
        content: "--Docs",
        metadata: {
          business_type: "approval_instance_id",
          data: {
            approval_instance_id: "41",
            approval_task_id: "91",
          },
        },
      },
    ],
  } as MessageItem;

  it("routes the invited user to the exact task in my tasks", () => {
    expect(isApprovalCenterNotification(pendingInvite)).toBe(true);
    expect(resolveApprovalCenterTarget(pendingInvite)).toEqual({
      tab: "my_tasks",
      taskId: 91,
      instanceId: 41,
    });
  });
});

/**
 * Business execution is a separate domain from the approval fact. An execution
 * outcome must never deep-link as if it were an approval waiting to be acted on.
 * Asserted on the exported set rather than on file text: labels and routing now
 * live in the same module, so a substring check would pass for the wrong reason.
 */
describe("business-execution notifications are not approval facts", () => {
  it.each([
    "approval_execute_failed",
    "resource_user_invite_effective",
    "resource_user_invite_failed",
  ])("keeps %s out of approval-center routing", (actionCode) => {
    expect(APPROVAL_CENTER_ACTION_CODES.has(actionCode)).toBe(false);
  });
});
