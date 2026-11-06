export function formatDateTime(isoStr?: string): string {
  if (!isoStr) return "--";
  try {
    const d = new Date(isoStr);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return isoStr;
  }
}

export const HIDDEN_DETAIL_KEYS = new Set([
  "business_key",
  "scenario_code",
  "exception_type",
  "node_code",
  "node_mode",
  "node_name",
  "node_order",
]);

export interface ConditionFieldMeta {
  label: string;
  values?: { value: string; label: string }[];
}

export const FIXED_ROLE_VALUES = [
  { value: "admin", label: "approvalPage.roleValue.admin" },
  { value: "tenant_admin", label: "approvalPage.roleValue.tenant_admin" },
  { value: "dept_admin", label: "approvalPage.roleValue.dept_admin" },
];

export const MENU_KEY_VALUES = [
  // Admin console menus
  { value: "board", label: "menu.board" },
  { value: "model", label: "menu.models" },
  { value: "log", label: "menu.log" },
  { value: "knowledge", label: "menu.knowledge" },
  { value: "build", label: "menu.skills" },
  { value: "evaluation", label: "menu.evaluation" },
  { value: "mark_task", label: "menu.annotation" },
  // Workbench menus
  { value: "home", label: "menu.workbenchHome" },
  { value: "apps", label: "menu.workbenchApps" },
  { value: "subscription", label: "menu.workbench1" },
  { value: "knowledge_space", label: "menu.workbench2" },
];

export const CONDITION_FIELD_META: Record<string, ConditionFieldMeta> = {
  applicant_role: {
    label: "approvalPage.condition.applicant_role",
    values: FIXED_ROLE_VALUES,
  },
  menu_key: {
    label: "approvalPage.condition.menu_key",
    values: MENU_KEY_VALUES,
  },
  space_type: {
    label: "approvalPage.condition.space_type",
    values: [
      { value: "public", label: "approvalPage.spaceType.public" },
      { value: "department", label: "approvalPage.spaceType.department" },
      { value: "team", label: "approvalPage.spaceType.team" },
    ],
  },
};

export const APPROVER_SOURCE_LABEL_KEYS: Record<string, string> = {
  direct_user: "approvalPage.approverSource.direct_user",
  department_admin: "approvalPage.approverSource.department_admin",
  tenant_admin: "approvalPage.approverSource.tenant_admin",
  channel_admin: "approvalPage.approverSource.channel_admin",
  space_admin: "approvalPage.approverSource.space_admin",
  knowledge_space_owner: "approvalPage.approverSource.knowledge_space_owner",
  knowledge_space_manager: "approvalPage.approverSource.knowledge_space_manager",
};

export type TFn = (key: string, opts?: Record<string, string>) => string;

export function conditionLabel(
  matchConfig: { field?: string; value?: string } | null | undefined,
  t: TFn,
  roleNameMap: Record<string, string> = {},
): string {
  if (!matchConfig?.field) return "";
  const meta = CONDITION_FIELD_META[matchConfig.field];
  const fieldLabel = meta ? t(meta.label, { defaultValue: matchConfig.field }) : matchConfig.field;
  const value = matchConfig.value ?? "";
  if (!value) return fieldLabel;
  const staticMatch = FIXED_ROLE_VALUES.find((v) => v.value === value) ?? meta?.values?.find((v) => v.value === value);
  const valLabel = staticMatch
    ? t(staticMatch.label, { defaultValue: staticMatch.value })
    : value.startsWith("role_")
      ? (roleNameMap[value] ?? `${t("approvalPage.systemRole")} #${value.slice(5)}`)
      : value;
  return `${fieldLabel} = ${valLabel}`;
}

export const APPROVER_SOURCE_OPTIONS = [
  { value: "direct_user", labelKey: "approvalPage.approverSource.direct_user" },
  { value: "department_admin", labelKey: "approvalPage.approverSource.department_admin" },
  { value: "knowledge_space_owner", labelKey: "approvalPage.approverSource.knowledge_space_owner" },
  { value: "knowledge_space_manager", labelKey: "approvalPage.approverSource.knowledge_space_manager" },
  { value: "channel_owner", labelKey: "approvalPage.approverSource.channel_owner" },
  { value: "channel_manager", labelKey: "approvalPage.approverSource.channel_manager" },
];
export interface ApproverSource {
  type: string;
  label?: string;
  user_ids?: number[];
  user_names?: string[];
  userNames?: string[];
}
interface ApprovalRole {
  id: number | string;
  role_name: string;
}
export function normalizeApprovalRoles(response: unknown): ApprovalRole[] {
  const payload = response as ApprovalRole[] | { data?: ApprovalRole[] } | null;
  return Array.isArray(payload) ? payload : (payload?.data ?? []);
}
