// F056 T023 / T024 / T025 — rendering rules of the system-audit page.
//
// The table cell, the CSV export and the selector labels all come from
// `auditRow.ts`; these tests pin the copy-independent rules (what goes where),
// with `t` returning the key so the assertions read as keys, not prose.

import { describe, expect, it } from "vitest";

import { actionToI18nKey, exportSystemLogDataApi, getAuditAppsApi, getLogsApi } from "@/controllers/API/log";
import {
  AuditRow,
  buildAuditCsv,
  renderObjectName,
  renderOperator,
  toAppOptions,
} from "@/pages/LogPage/systemLog/auditRow";
import { beforeEach, vi } from "vitest";

const t = (key: string, opts?: Record<string, unknown>) => {
  if (key === "log.versionLabel") return `v${opts?.no}`;
  return key;
};

const base: AuditRow = {
  id: "row-1",
  operator_id: 9,
  operator_name: "olga",
  create_time: "2026-09-16T10:00:00",
  action: "app.publish",
  target_type: "app",
  target_id: "app-1",
  object_name: "Alpha",
  tenant_id: 2,
};

describe("object cell", () => {
  it("shows name + slug for a hosted-application row", () => {
    expect(renderObjectName({ ...base, app_id: "app-1", app_name: "Alpha", app_slug: "alpha" }, t)).toBe(
      "Alpha (alpha)",
    );
  });

  it("marks a deleted application and keeps the name snapshot", () => {
    // The app row is gone from the live table; the audit row's object_name is
    // the only name left (AC-21).
    const row = { ...base, app_id: "app-1", app_name: null, app_slug: "alpha", app_state: "deleted" };
    expect(renderObjectName(row, t)).toBe("Alpha (alpha) · log.deletedSuffix");
  });

  it("appends the version a release event was about", () => {
    const row = { ...base, app_id: "app-1", app_name: "Alpha", app_slug: "alpha", version_no: 3 };
    expect(renderObjectName(row, t)).toBe("Alpha (alpha) · v3");
  });

  it("falls back to the legacy rule for non-application rows", () => {
    expect(renderObjectName({ ...base, object_name: null, target_id: "t-9" }, t)).toBe("t-9");
    expect(renderObjectName({ ...base, object_name: null, target_id: null }, t)).toBe("log.objectTypeEnum.none");
  });
});

describe("operator cell", () => {
  it("renders a natural person as a single line", () => {
    expect(renderOperator(base, t)).toEqual({ primary: "olga", secondary: null });
  });

  it("renders a service account with key mask and the application owner (AC-17)", () => {
    const row: AuditRow = {
      ...base,
      operator_id: 0,
      operator_name: "ci-bot",
      operator_kind: "service_account",
      operator_key_mask: "bsk_****ab12",
      app_owner_name: "owner-olga",
    };
    expect(renderOperator(row, t)).toEqual({
      primary: "ci-bot (bsk_****ab12)",
      secondary: "log.serviceAccount · log.appOwner: owner-olga",
    });
  });

  it("never invents a mask when the writer recorded none", () => {
    const row: AuditRow = { ...base, operator_id: 0, operator_name: "ci-bot", operator_kind: "service_account" };
    expect(renderOperator(row, t).primary).toBe("ci-bot");
  });

  it("labels a system trigger as system", () => {
    expect(renderOperator({ ...base, operator_id: 0, operator_name: null }, t).primary).toBe("system");
  });
});

describe("application selector options", () => {
  it("labels name (slug) and flags deleted apps; drops rows without an id", () => {
    const options = toAppOptions(
      [
        { id: "a1", name: "Alpha", slug: "alpha", state: "online" },
        { id: "a2", name: "Beta", slug: "beta", state: "deleted" },
        { id: "", name: "Ghost", slug: "ghost", state: "online" },
      ],
      t,
    );
    expect(options).toEqual([
      { label: "Alpha (alpha)", value: "a1" },
      { label: "Beta (beta) · log.deletedSuffix", value: "a2" },
    ]);
  });
});

describe("csv export", () => {
  const row: AuditRow = {
    ...base,
    app_id: "app-1",
    app_name: "Alpha",
    app_slug: "alpha",
    tenant_name: "Acme",
    ip_address: "10.0.0.1",
    note: "n",
    reason: "r",
  };

  it("uses the table columns and adds the tenant column only when asked (AC-30 / AC-32)", () => {
    const withTenant = buildAuditCsv([row], t, actionToI18nKey, { withTenant: true });
    const without = buildAuditCsv([row], t, actionToI18nKey, { withTenant: false });
    expect(withTenant[0]).toEqual([
      "log.auditId",
      "log.username",
      "log.operationTime",
      "log.systemModule",
      "log.operationAction",
      "log.objectType",
      "log.operationObject",
      "log.appSlug",
      "log.tenant",
      "log.ipAddress",
      "log.remark",
      "log.reason",
    ]);
    expect(withTenant[1]).toEqual([
      "row-1",
      "olga",
      "2026-09-16 10:00:00",
      "log.systemIdEnum.app",
      "log.eventTypeEnum.appPublish",
      "log.objectTypeEnum.app",
      "Alpha (alpha)",
      "alpha",
      "Acme",
      "10.0.0.1",
      "n",
      "r",
    ]);
    expect(without[0]).not.toContain("log.tenant");
    expect(without[1]).toHaveLength(withTenant[1].length - 1);
  });

  it("folds the service-account annotation into the operator column", () => {
    const sa: AuditRow = {
      ...row,
      operator_id: 0,
      operator_name: "ci-bot",
      operator_kind: "service_account",
      operator_key_mask: "bsk_****ab12",
    };
    const [, line] = buildAuditCsv([sa], t, actionToI18nKey, { withTenant: false });
    expect(line[1]).toBe("ci-bot (bsk_****ab12) · log.serviceAccount");
  });
});

// --- API layer: the query string the page sends ------------------------------

const requestMocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/controllers/request", () => ({
  default: requestMocks,
  captureAndAlertRequestErrorHoc: (promise: Promise<unknown>) => promise,
}));

describe("audit API params", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requestMocks.get.mockResolvedValue({ data: [], total: 0 });
  });

  it("sends target_app_id / tenant_id and drops empty filters", async () => {
    await getLogsApi({ page: 2, pageSize: 20, userIds: [1, 2], groupId: "", targetAppId: "app-1", tenantId: 3 });
    const [url, config] = requestMocks.get.mock.calls[0];
    expect(url).toBe("/api/v1/audit");
    expect(config.params).toEqual({
      page: 2,
      limit: 20,
      operator_ids: [1, 2],
      target_app_id: "app-1",
      tenant_id: 3,
    });
    expect(config.params).not.toHaveProperty("group_ids");
    expect(config.params).not.toHaveProperty("system_id");
  });

  it("export uses the same filter names as the list, without pagination", async () => {
    await exportSystemLogDataApi({ userIds: [], moduleId: "app", action: "app.publish", targetAppId: "app-1" });
    const [url, config] = requestMocks.get.mock.calls[0];
    expect(url).toBe("/api/v1/audit/export/data");
    expect(config.params).toEqual({ system_id: "app", event_type: "app.publish", target_app_id: "app-1" });
    expect(config.params).not.toHaveProperty("page");
  });

  it("app selector searches by keyword", async () => {
    requestMocks.get.mockResolvedValue([]);
    await getAuditAppsApi("sal");
    const [url, config] = requestMocks.get.mock.calls[0];
    expect(url).toBe("/api/v1/audit/apps");
    expect(config.params).toEqual({ keyword: "sal", limit: 20 });
  });
});
