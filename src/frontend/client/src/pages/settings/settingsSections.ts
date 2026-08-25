import { Outlined } from "bisheng-icons";
import type { ComponentType } from "react";
import type { ApprovalCenterTab } from "~/api/approval";

/** Sections in two labeled groups: personal settings first, then approval + notifications. */
export type SettingsPageSection =
  | "my-tasks"
  | "my-requests"
  | "notifications"
  | "account"
  | "general";

export interface SettingsNavItem {
  key: SettingsPageSection;
  labelKey: string;
  icon: ComponentType<{ className?: string }>;
}

export interface SettingsNavGroup {
  /** Group caption above the items — same style as the home sidebar's date labels. */
  labelKey: string;
  items: SettingsNavItem[];
}

export const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  {
    labelKey: "com_settings_group_personal",
    items: [
      { key: "account", labelKey: "com_account_info_title", icon: Outlined.PeopleRound },
      { key: "general", labelKey: "com_settings_general", icon: Outlined.Setting },
    ],
  },
  {
    labelKey: "com_settings_group_messages",
    items: [
      { key: "my-tasks", labelKey: "com_approval_my_approval", icon: Outlined.ApprovalTodo },
      { key: "my-requests", labelKey: "com_approval_my_requests", icon: Outlined.ApprovalSubmitted },
      { key: "notifications", labelKey: "com_message_approval_notifications", icon: Outlined.Bell },
    ],
  },
];

export const SETTINGS_NAV_ITEMS: SettingsNavItem[] = SETTINGS_NAV_GROUPS.flatMap(
  (group) => group.items,
);

export const DEFAULT_SETTINGS_SECTION: SettingsPageSection = "account";

export function isSettingsPageSection(value: unknown): value is SettingsPageSection {
  return SETTINGS_NAV_ITEMS.some((item) => item.key === value);
}

/** The two approval sections map onto the approval-center tabs the pane understands. */
export function approvalTabOf(section: SettingsPageSection): ApprovalCenterTab | null {
  if (section === "my-tasks") return "my_tasks";
  if (section === "my-requests") return "my_requests";
  return null;
}

/**
 * Where the avatar entry lands: whatever is actually waiting on the user wins,
 * otherwise the plain settings landing. Counts are already loaded at click time,
 * so this never flashes a wrong section.
 */
export function settingsLandingPath(pendingApprovalCount: number, unreadCount: number): string {
  if (pendingApprovalCount > 0) return "/settings/my-tasks";
  if (unreadCount > 0) return "/settings/notifications";
  return `/settings/${DEFAULT_SETTINGS_SECTION}`;
}
