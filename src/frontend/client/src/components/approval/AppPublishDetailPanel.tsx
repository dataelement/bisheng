import type { ApprovalInstanceDetail, ApprovalTaskDetail } from "~/api/approval";
import { cn } from "~/utils";
import {
  DetailHeader,
  formatSerialNo,
  formatTime,
  InfoGrid,
  type LocalizeFn,
} from "./ApprovalDetailPrimitives";

/** Backend scenario code (app_publish_scenario_handler.SCENARIO_CODE). */
export const APP_PUBLISH_SCENARIO_CODE = "app_publish_request";

export function isAppPublishScenario(scenarioCode?: string | null): boolean {
  return String(scenarioCode ?? "").toLowerCase() === APP_PUBLISH_SCENARIO_CODE;
}

/** One declared platform capability, normalized from the (deferred) backend shape. */
type CapabilityEntry = {
  type: string;
  name: string;
  description: string;
};

/** One visibility grant in the release's visibility snapshot (owned by F056). */
type VisibilityEntry = {
  type: string;
  name: string;
};

export interface AppPublishDetailPanelProps {
  detail: ApprovalTaskDetail | ApprovalInstanceDetail;
  scope: "task" | "instance";
  localize: LocalizeFn;
  onBack?: () => void;
}

function asText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "object") return "";
  return String(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function toCapabilityEntries(value: unknown): CapabilityEntry[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return { type: "", name: item, description: "" };
    const record = asRecord(item);
    return {
      type: asText(record.type),
      name: asText(record.name) || asText(record.code) || asText(record.id),
      description: asText(record.description),
    };
  });
}

function toVisibilityEntries(value: unknown): VisibilityEntry[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    if (typeof item === "string") return { type: "", name: item };
    const record = asRecord(item);
    return {
      type: asText(record.type) || asText(record.subject_type),
      name: asText(record.name) || asText(record.subject_name) || asText(record.id),
    };
  });
}

function SectionTitle({ children }: { children: string }) {
  return <div className="mb-2 text-[14px] font-medium text-text-primary">{children}</div>;
}

function SectionEmpty({ children }: { children: string }) {
  return <div className="rounded-lg bg-[#fafbfc] p-4 text-[13px] text-[#86909c]">{children}</div>;
}

/**
 * The app-publish approval card (F055 AC-24): four regions instead of the generic
 * two-column grid, because `build_detail` ships structured sub-trees that the
 * generic grid would print as `[object Object]` under raw English key names.
 *
 * Only `detail_snapshot` is read — never `payload_snapshot`, which the same API
 * response also carries and which holds internal fields (tenant_id, deployment_id…)
 * that must not reach an approver's screen.
 */
export function AppPublishDetailPanel({ detail, scope, localize, onBack }: AppPublishDetailPanelProps) {
  const snapshot: Record<string, unknown> = detail.detail_snapshot ?? {};
  const instanceId = scope === "task" ? detail.instance_id ?? null : detail.instance_id ?? detail.id ?? null;
  const serialNo = instanceId ? formatSerialNo(instanceId, detail.create_time) : "--";
  const instanceStatus = "instance_status" in detail ? detail.instance_status : undefined;

  const appName = asText(snapshot.app_name) || detail.business_name || "--";

  const sourceCode = asText(snapshot.source).toLowerCase();
  const sourceText =
    sourceCode === "cli"
      ? localize("com_approval_app_publish_source_cli")
      : sourceCode === "platform" || sourceCode === "builder"
        ? localize("com_approval_app_publish_source_platform")
        : asText(snapshot.source) || "--";

  const releaseKind = asText(snapshot.release_kind).toLowerCase();
  const releaseKindText =
    releaseKind === "initial"
      ? localize("com_approval_app_publish_kind_initial")
      : releaseKind === "iteration"
        ? localize("com_approval_app_publish_kind_iteration")
        : asText(snapshot.release_kind_text) || "--";

  const versionNo = asText(snapshot.version_no);

  const basicRows: [string, string][] = [
    [localize("com_approval_field_serial_no"), serialNo],
    [localize("com_approval_app_publish_field_app_name"), appName],
    [localize("com_approval_app_publish_field_owner"), asText(snapshot.owner_user_name) || detail.applicant_user_name || "--"],
    [localize("com_approval_app_publish_field_source"), sourceText],
    [localize("com_approval_app_publish_field_release_kind"), releaseKindText],
    [localize("com_approval_app_publish_field_version"), versionNo ? `v${versionNo}` : "--"],
    [localize("com_approval_app_publish_field_submitted_at"), formatTime(asText(snapshot.submitted_at) || detail.create_time)],
  ];

  // AC-16: says why the request skipped the department approval node, so an
  // approver is not left wondering. Deliberately names no administrator role —
  // who the fallback approver is differs between single- and multi-tenant setups.
  const approverNote = asText(snapshot.approver_note);
  const approverNoteText =
    approverNote === "no_department_admin_source"
      ? localize("com_approval_app_publish_note_no_department_admin")
      : approverNote;

  const capabilities = toCapabilityEntries(snapshot.capabilities);
  const visibility = toVisibilityEntries(snapshot.visibility_snapshot);

  const tier = asRecord(snapshot.tier);
  const cpuMillicores = Number(tier.cpu_millicores);
  const memoryMb = Number(tier.memory_mb);
  const tierRows: [string, string][] = [
    [
      localize("com_approval_app_publish_field_tier_name"),
      asText(tier.name) || asText(tier.code) || asText(snapshot.tier_name) || "--",
    ],
    [
      localize("com_approval_app_publish_field_cpu"),
      Number.isFinite(cpuMillicores) && cpuMillicores > 0
        ? localize("com_approval_app_publish_cpu_cores", { value: String(cpuMillicores / 1000) })
        : "--",
    ],
    [
      localize("com_approval_app_publish_field_memory"),
      Number.isFinite(memoryMb) && memoryMb > 0 ? `${memoryMb} MB` : "--",
    ],
  ];

  return (
    <div className="space-y-5">
      <DetailHeader
        title={appName}
        status={detail.status}
        instanceStatus={instanceStatus}
        scope={scope}
        serialNo={serialNo}
        scenarioName={detail.scenario_name || detail.scenario_code}
        createTime={detail.create_time}
        localize={localize}
        onBack={onBack}
      />

      {/* ① Basic information */}
      <div>
        <SectionTitle>{localize("com_approval_section_basic_info")}</SectionTitle>
        <InfoGrid rows={basicRows} />
        {approverNoteText && (
          <div className="mt-2 rounded-lg bg-[#fff7e8] px-3 py-2 text-[12px] text-[#ff7d00] break-all">
            {approverNoteText}
          </div>
        )}
      </div>

      {/* ② Declared platform capabilities */}
      <div>
        <SectionTitle>{localize("com_approval_app_publish_section_capabilities")}</SectionTitle>
        {capabilities.length === 0 ? (
          <SectionEmpty>{localize("com_approval_app_publish_capabilities_empty")}</SectionEmpty>
        ) : (
          <div className="overflow-hidden rounded-lg border border-[#f2f3f5]">
            {capabilities.map((capability, index) => (
              <div
                key={`${capability.type}-${capability.name}-${index}`}
                className={cn("bg-white px-3 py-2", index > 0 && "border-t border-[#f2f3f5]")}
              >
                <div className="text-[14px] font-medium text-text-primary break-all">{capability.name || "--"}</div>
                {(capability.type || capability.description) && (
                  <div className="mt-0.5 text-[12px] text-[#86909c] break-all">
                    {[capability.type, capability.description].filter(Boolean).join(" · ")}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ③ Visibility snapshot */}
      <div>
        <SectionTitle>{localize("com_approval_app_publish_section_visibility")}</SectionTitle>
        {visibility.length === 0 ? (
          <SectionEmpty>{localize("com_approval_app_publish_visibility_empty")}</SectionEmpty>
        ) : (
          <div className="flex flex-wrap gap-2 rounded-lg bg-[#fafbfc] p-4">
            {visibility.map((entry, index) => (
              <span
                key={`${entry.type}-${entry.name}-${index}`}
                className="rounded-full border border-[#e5e6eb] bg-white px-3 py-1 text-[12px] text-[#4e5969] break-all"
              >
                {entry.name || "--"}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ④ Resource tier */}
      <div>
        <SectionTitle>{localize("com_approval_app_publish_section_tier")}</SectionTitle>
        <InfoGrid rows={tierRows} />
      </div>
    </div>
  );
}
