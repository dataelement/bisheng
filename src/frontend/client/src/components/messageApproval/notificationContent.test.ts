import en from "~/locales/en/translation.json";
import ja from "~/locales/ja/translation.json";
import zhHans from "~/locales/zh-Hans/translation.json";
import {
    APPROVAL_CENTER_ACTION_CODES,
    NOTIFICATION_ACTION_TEXT_KEYS,
    isApprovalMessageType,
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
