import en from "~/locales/en/translation.json";
import ja from "~/locales/ja/translation.json";
import zhHans from "~/locales/zh-Hans/translation.json";
import {
    APPROVAL_CENTER_ACTION_CODES,
    NOTIFICATION_ACTION_TEXT_KEYS,
    isApprovalMessageType,
    resolveApprovalCenterTarget,
} from "./notificationContent";

// F056 AC-43: an administrator stopping / resuming someone else's hosted app
// sends the owner a statement. These codes must render copy in every language
// and must never grow an approval button.
const ADMIN_STATE_CHANGE_CODES = ["app_stopped_by_admin", "app_resumed_by_admin"] as const;

describe("hosted app admin stop / resume notifications", () => {
    it.each(ADMIN_STATE_CHANGE_CODES)("maps %s to a copy key shipped in all three languages", (code) => {
        const key = NOTIFICATION_ACTION_TEXT_KEYS[code];
        expect(key).toBe(`com_notifications_action_${code}`);
        for (const bundle of [zhHans, en, ja]) {
            const copy = (bundle as Record<string, unknown>)[key];
            expect(typeof copy).toBe("string");
            expect(copy).toEqual(expect.stringContaining("{{target}}"));
        }
    });

    it.each(ADMIN_STATE_CHANGE_CODES)("%s is a statement, not an approval-centre item", (code) => {
        expect(APPROVAL_CENTER_ACTION_CODES.has(code)).toBe(false);
        expect(isApprovalMessageType("notify", code)).toBe(false);
    });
});


describe("approval notification destinations", () => {
    it.each(["approval_instance_withdrawn", "approval_instance_cancelled"])("opens %s in the recipient approver's processed tasks", (actionCode) => {
        const target = resolveApprovalCenterTarget({
            action_code: actionCode, message_type: "notify",
            content: [{ type: "system_text", content: actionCode }, { type: "business_url", content: "demo", metadata: { business_type: "approval_instance_id", data: { approval_instance_id: "42" } } }],
        } as Parameters<typeof resolveApprovalCenterTarget>[0]);
        expect(target).toEqual({ tab: "my_tasks", taskId: null, instanceId: 42 });
    });
    it("keeps explicit task and instance identities distinct", () => {
        const target = resolveApprovalCenterTarget({
            action_code: "approval_task_pending", message_type: "notify",
            content: [{ type: "system_text", content: "approval_task_pending" }, { type: "business_url", content: "demo", metadata: { business_type: "approval_instance_id", data: { approval_instance_id: "42", approval_task_id: "87" } } }],
        } as Parameters<typeof resolveApprovalCenterTarget>[0]);
        expect(target).toEqual({ tab: "my_tasks", taskId: 87, instanceId: 42 });
    });
});
