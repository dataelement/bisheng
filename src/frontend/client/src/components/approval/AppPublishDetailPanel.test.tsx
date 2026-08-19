import { render, screen } from "@testing-library/react";
import type { ApprovalTaskDetail } from "~/api/approval";
import { AppPublishDetailPanel, isAppPublishScenario } from "./AppPublishDetailPanel";
import type { LocalizeFn } from "./ApprovalDetailPrimitives";

/** Echoes the key back so assertions read as the contract, plus the interpolated value. */
const localize: LocalizeFn = (key, options) =>
  options && "value" in options ? `${String(key)}:${String(options.value)}` : String(key);

/** What app_publish_scenario_handler.build_detail ships (18 keys, no tenant field). */
function buildDetail(overrides: Partial<ApprovalTaskDetail> = {}): ApprovalTaskDetail {
  return {
    task_id: 7,
    instance_id: 42,
    scenario_code: "app_publish_request",
    scenario_name: "app publish",
    business_name: "form-survey",
    status: "pending",
    instance_status: "pending",
    applicant_user_name: "alice",
    create_time: "2026-08-19T10:00:00",
    detail_snapshot: {
      scenario_code: "app_publish_request",
      app_name: "form-survey",
      release_kind_text: "raw-backend-text",
      tier_name: "light",
      app_id: "17",
      app_slug: "form-survey",
      owner_user_id: 3,
      owner_user_name: "alice",
      source: "cli",
      release_kind: "initial",
      version_id: "v-1",
      version_no: 3,
      submitted_at: "2026-08-19T10:00:00",
      tier: { code: "light", name: "Light", cpu_millicores: 500, memory_mb: 512 },
      capabilities: [],
      visibility_snapshot: [],
      schema_change: null,
      approver_note: "no_department_admin_source",
    },
    // Also delivered by the API and deliberately never rendered by this panel.
    payload_snapshot: { tenant_id: 99, deployment_id: 1234, app_name: "form-survey" },
    ...overrides,
  };
}

describe("AppPublishDetailPanel", () => {
  it("recognises only the app publish scenario code", () => {
    expect(isAppPublishScenario("app_publish_request")).toBe(true);
    expect(isAppPublishScenario("APP_PUBLISH_REQUEST")).toBe(true);
    expect(isAppPublishScenario("menu_access_request")).toBe(false);
    expect(isAppPublishScenario(undefined)).toBe(false);
  });

  it("renders the four regions and unpacks the tier instead of stringifying it", () => {
    const { container } = render(
      <AppPublishDetailPanel detail={buildDetail()} scope="task" localize={localize} />,
    );

    // Region 1 — basic information, with the release kind localized from the code
    // rather than trusting the backend's pre-rendered text.
    expect(screen.getByText("com_approval_section_basic_info")).toBeInTheDocument();
    expect(screen.getByText("com_approval_app_publish_kind_initial")).toBeInTheDocument();
    expect(screen.getByText("com_approval_app_publish_source_cli")).toBeInTheDocument();
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(container.textContent).not.toContain("raw-backend-text");

    // Regions 2 and 3 — empty this round, so they say so instead of rendering nothing.
    expect(screen.getByText("com_approval_app_publish_capabilities_empty")).toBeInTheDocument();
    expect(screen.getByText("com_approval_app_publish_visibility_empty")).toBeInTheDocument();

    // Region 4 — the tier dict expanded into name / cpu / memory.
    expect(screen.getByText("Light")).toBeInTheDocument();
    expect(screen.getByText("com_approval_app_publish_cpu_cores:0.5")).toBeInTheDocument();
    expect(screen.getByText("512 MB")).toBeInTheDocument();
    expect(container.textContent).not.toContain("[object Object]");
  });

  it("never spills payload_snapshot onto the card", () => {
    const { container } = render(
      <AppPublishDetailPanel detail={buildDetail()} scope="task" localize={localize} />,
    );
    expect(container.textContent).not.toContain("99");
    expect(container.textContent).not.toContain("1234");
    expect(container.textContent).not.toContain("tenant");
  });

  it("explains a skipped department node without naming an administrator role", () => {
    render(<AppPublishDetailPanel detail={buildDetail()} scope="task" localize={localize} />);
    expect(
      screen.getByText("com_approval_app_publish_note_no_department_admin"),
    ).toBeInTheDocument();
  });

  it("lists declared capabilities and visibility entries when they arrive", () => {
    const detail = buildDetail();
    detail.detail_snapshot = {
      ...detail.detail_snapshot,
      capabilities: [{ type: "model", name: "qwen-max", description: "chat model" }],
      visibility_snapshot: [{ type: "department", name: "R&D" }],
    };
    const { container } = render(
      <AppPublishDetailPanel detail={detail} scope="task" localize={localize} />,
    );
    expect(screen.getByText("qwen-max")).toBeInTheDocument();
    expect(screen.getByText("model · chat model")).toBeInTheDocument();
    expect(screen.getByText("R&D")).toBeInTheDocument();
    expect(container.textContent).not.toContain("[object Object]");
  });

  it("falls back to placeholders when the tier is missing", () => {
    const detail = buildDetail();
    detail.detail_snapshot = { ...detail.detail_snapshot, tier: {}, tier_name: "" };
    const { container } = render(
      <AppPublishDetailPanel detail={detail} scope="task" localize={localize} />,
    );
    expect(container.textContent).not.toContain("NaN");
    expect(container.textContent).not.toContain("[object Object]");
  });
});
