import type { ApprovalInstanceDetail, ApprovalTaskDetail } from "~/api/approval";
import { useLocalize } from "~/hooks";

export const RESOURCE_USER_INVITE_SCENARIO_CODE = "resource_user_invite_confirmation";

interface ResourceUserInviteBusinessContentProps {
  detail: ApprovalTaskDetail | ApprovalInstanceDetail;
  localize: ReturnType<typeof useLocalize>;
}

interface BusinessContentRow {
  label: string;
  value: string;
}

function localizedEnum(
  namespace: string,
  value: unknown,
  localize: ReturnType<typeof useLocalize>,
): string {
  if (typeof value !== "string" || !value) return "--";
  return localize(`${namespace}_${value}`, { defaultValue: value }) as string;
}

export function buildResourceUserInviteBusinessRows(
  detail: ApprovalTaskDetail | ApprovalInstanceDetail,
  localize: ReturnType<typeof useLocalize>,
): BusinessContentRow[] | null {
  if (detail.scenario_code !== RESOURCE_USER_INVITE_SCENARIO_CODE) return null;

  const snapshot = detail.detail_snapshot ?? detail.payload_snapshot ?? {};
  const roleName = typeof snapshot.role_name === "string" && snapshot.role_name
    ? snapshot.role_name
    : localizedEnum("com_approval_invite_permission", snapshot.relation, localize);

  return [
    {
      label: localize("com_approval_invite_field_resource_type"),
      value: localizedEnum("com_approval_invite_resource_type", snapshot.resource_type, localize),
    },
    {
      label: localize("com_approval_invite_field_resource_name"),
      value: typeof snapshot.resource_name === "string" && snapshot.resource_name
        ? snapshot.resource_name
        : detail.business_name || "--",
    },
    {
      label: localize("com_approval_invite_field_target_user"),
      value: typeof snapshot.target_user_name === "string" && snapshot.target_user_name
        ? snapshot.target_user_name
        : "--",
    },
    {
      label: localize("com_approval_invite_field_permission"),
      value: roleName,
    },
  ];
}

export function ResourceUserInviteBusinessContent({
  detail,
  localize,
}: ResourceUserInviteBusinessContentProps) {
  const rows = buildResourceUserInviteBusinessRows(detail, localize);
  if (!rows) return null;

  return (
    <div>
      <div className="mb-2 text-[14px] font-medium text-text-primary">
        {localize("com_approval_section_business_content")}
      </div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-[#f2f3f5] bg-[#f2f3f5]">
        {rows.map((row) => (
          <div key={row.label} className="bg-white px-3 py-2">
            <div className="text-[12px] text-[#86909c]">{row.label}</div>
            <div className="mt-1 text-[14px] text-text-primary break-all">{row.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
