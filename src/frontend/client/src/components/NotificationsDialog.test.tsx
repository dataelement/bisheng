import type { MessageItem } from "~/api/message";
import {
  isApprovalCenterNotification,
  resolveApprovalCenterNotificationTarget,
} from "./notificationApprovalRouting";

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
    expect(resolveApprovalCenterNotificationTarget(pendingInvite)).toEqual({
      tab: "my_tasks",
      taskId: 91,
      instanceId: 41,
    });
  });
});
