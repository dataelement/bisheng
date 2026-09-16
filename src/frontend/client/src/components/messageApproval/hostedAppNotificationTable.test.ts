import en from "~/locales/en/translation.json";
import ja from "~/locales/ja/translation.json";
import zhHans from "~/locales/zh-Hans/translation.json";
import {
    APPROVAL_CENTER_ACTION_CODES,
    NOTIFICATION_ACTION_TEXT_KEYS,
    isApprovalMessageType,
} from "./notificationContent";

/**
 * F056 T033 — the receiving half of the §3.0.3 table (AC-39 ~ AC-42).
 *
 * The backend half is asserted in
 * `src/backend/test/app_publish/test_notification_table_acceptance.py`: which
 * events send, which must not, and that a failed send never blocks the action.
 * None of that says the recipient can *read* the message. Copy is where these
 * tables actually break — a message whose action code has no key renders as a
 * raw `com_notifications_action_…` string, or as nothing at all, and only in
 * the language nobody on the team is testing in.
 *
 * So every code the backend can send is checked against all three bundles, and
 * the statement/request split is checked with it: the row grows an approval
 * button from the *message type*, so a publish notice typed as a request would
 * show a button that errors when pressed.
 */

/** Sent by F055's publish pipeline (AC-42) and by F056's governance hook (AC-43). */
const HOSTED_APP_STATEMENT_CODES = [
    "app_publish_pending_capacity",
    "app_publish_deploy_failed",
    "app_publish_iteration_failed",
    "app_stopped_by_admin",
    "app_resumed_by_admin",
] as const;

/** Sent by the approval engine for a hosted-application publish request. */
const APPROVAL_ENGINE_CODES = [
    // AC-40: request created → approvers; approved / rejected → owner;
    // owner withdrew → the approvers who held a task.
    "approval_task_pending",
    "approval_instance_approved",
    "approval_task_rejected",
    "approval_instance_withdrawn",
    // AC-41: the application was deleted, so its in-flight request was cancelled.
    "approval_instance_cancelled",
] as const;

const ALL_CODES = [...HOSTED_APP_STATEMENT_CODES, ...APPROVAL_ENGINE_CODES];

const BUNDLES: Array<[string, Record<string, unknown>]> = [
    ["zh-Hans", zhHans as Record<string, unknown>],
    ["en", en as Record<string, unknown>],
    ["ja", ja as Record<string, unknown>],
];

/** What `NotificationRow` resolves an action code to, including its fallback. */
function copyKeyFor(code: string): string {
    return NOTIFICATION_ACTION_TEXT_KEYS[code] || `com_notifications_action_${code}`;
}

describe("§3.0.3 — every hosted-application notification is readable", () => {
    it.each(ALL_CODES)("%s has copy in zh-Hans, en and ja", (code) => {
        const key = copyKeyFor(code);
        for (const [language, bundle] of BUNDLES) {
            const copy = bundle[key];
            expect(`${language}:${typeof copy}`).toBe(`${language}:string`);
            expect(`${language}:${copy as string}`.length).toBeGreaterThan(language.length + 1);
        }
    });

    it.each(ALL_CODES)("%s names the application it is about", (code) => {
        // Without `{{target}}` the owner gets "your application was stopped"
        // and has to guess which one — they may own several.
        const key = copyKeyFor(code);
        for (const [, bundle] of BUNDLES) {
            expect(bundle[key]).toEqual(expect.stringContaining("{{target}}"));
        }
    });
});

describe("§3.0.3 — statements stay statements", () => {
    it.each(HOSTED_APP_STATEMENT_CODES)("%s carries no approval action", (code) => {
        // AC-39: these are notifications; the buttons live on the publish face
        // and in the approval centre.
        expect(APPROVAL_CENTER_ACTION_CODES.has(code)).toBe(false);
        expect(isApprovalMessageType("notify", code)).toBe(false);
    });

    it("keeps the approval-centre codes in the approval centre", () => {
        // The other direction: an approver's task has to remain actionable, so
        // the same split that silences the publish notices must not silence it.
        expect(APPROVAL_CENTER_ACTION_CODES.has("approval_task_pending")).toBe(true);
    });

    it("treats a cancelled-by-delete notice as a statement", () => {
        // AC-41: the request is already gone — there is nothing left to decide,
        // and a button here would fail on press.
        expect(isApprovalMessageType("notify", "approval_instance_cancelled")).toBe(false);
    });
});

describe("§3.0.3 — the four silent rows have no copy to render", () => {
    // AC-44. Copy is the last place a decision like this survives: a leftover
    // "your key was revoked" string is an invitation to wire up the sender.
    const FORBIDDEN_FRAGMENTS = [
        "app_key_issued",
        "app_key_revoked",
        "app_capability_revoked",
        "app_resource_released",
        "app_listed_in_square",
        "app_visibility_granted",
    ];

    it.each(FORBIDDEN_FRAGMENTS)("no action code or copy key exists for %s", (fragment) => {
        expect(NOTIFICATION_ACTION_TEXT_KEYS[fragment]).toBeUndefined();
        for (const [, bundle] of BUNDLES) {
            expect(bundle[`com_notifications_action_${fragment}`]).toBeUndefined();
        }
    });
});
