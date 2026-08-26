import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
// store.mobileSystemMenuOpenState is a shared legacy atom (same usage as Subscription/knowledge pages).
// eslint-disable-next-line no-restricted-imports
import { useSetRecoilState } from "recoil";
import { ApprovalPane } from "~/components/approval/ApprovalPane";
import { NotificationPane } from "~/components/messageApproval/NotificationPane";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useNotificationCount } from "~/hooks/useNotificationCount";
import store from "~/store";
import { cn } from "~/utils";
import { AccountPane } from "./sections/AccountPane";
import { GeneralSection } from "~/components/Settings/sections/GeneralSection";
import {
  approvalTabOf,
  DEFAULT_SETTINGS_SECTION,
  isSettingsPageSection,
  SETTINGS_NAV_GROUPS,
  SETTINGS_NAV_ITEMS,
  type SettingsPageSection,
} from "./settingsSections";

function NavCountBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="flex h-4 min-w-[16px] shrink-0 items-center justify-center rounded-full bg-[#f53f3f] px-1 text-[11px] leading-none text-white tabular-nums">
      {count > 99 ? "99+" : count}
    </span>
  );
}

/**
 * 设置 page — replaces the old SettingsDialog + MessageApprovalDialog pair with one
 * routed page (/settings/:section). One flat nav: approval + notifications first,
 * personal settings after the divider.
 *
 * Ownership stays strict (same as the retired dialog): an approval that still needs
 * handling lives only under 我的审批-待我处理, and 通知 only informs — nothing here
 * decrements the pending count except a real decision.
 */
export default function SettingsPage() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const isMobile = usePrefersMobileLayout();
  const setSystemMenuOpen = useSetRecoilState(store.mobileSystemMenuOpenState);
  const { section: rawSection } = useParams<{ section?: string }>();
  const { unreadCount, pendingApprovalCount, refreshCount } = useNotificationCount();

  // Compact (<768px) approval master-detail state, owned here so the nav can reset it.
  const [compactView, setCompactView] = useState<"list" | "detail">("list");
  /** Set when a notification jumps into an approval detail. */
  const [deepLink, setDeepLink] = useState<{ taskId?: number | null; instanceId?: number | null } | null>(null);

  const section: SettingsPageSection = isSettingsPageSection(rawSection)
    ? rawSection
    : DEFAULT_SETTINGS_SECTION;

  // Section changes can change both counts (decisions, read state) — keep the badges fresh.
  useEffect(() => {
    void refreshCount();
  }, [section, refreshCount]);

  if (!isSettingsPageSection(rawSection)) {
    return <Navigate to={`/settings/${DEFAULT_SETTINGS_SECTION}`} replace />;
  }

  // Sidebar/deep-link moves REPLACE the history entry: settings keeps exactly one
  // entry, so 返回 (and the browser's own back) leads to whatever page the user was
  // on before opening settings, never through the sections they browsed here.
  const goToSection = (next: SettingsPageSection) => {
    setCompactView("list");
    setDeepLink(null);
    navigate(`/settings/${next}`, { replace: true });
  };

  const approvalTab = approvalTabOf(section);
  const isApproval = approvalTab != null;
  const isNotifications = section === "notifications";

  const navBadge = (key: SettingsPageSection) =>
    key === "my-tasks" ? pendingApprovalCount : key === "notifications" ? unreadCount : 0;

  // Every content pane carries the active section's name as its title (desktop only —
  // the mobile top bar + tabs already announce the section). Style and top spacing
  // mirror the nav's 设置 heading (text-base leading-8 at 16px from the top).
  const activeNavItem = SETTINGS_NAV_ITEMS.find((item) => item.key === section);
  const sectionTitle = activeNavItem ? localize(activeNavItem.labelKey) : "";
  const paneTitleClass = "text-base font-semibold leading-8 text-text-1";

  const content = isApproval ? (
    <div className="flex min-h-0 flex-1 flex-col">
      <h2 className={cn("hidden shrink-0 px-5 pt-4 md:block", paneTitleClass)}>
        {sectionTitle}
      </h2>
      <div
        className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[300px_minmax(0,1fr)]"
      >
        <ApprovalPane
          open
          activeTab={approvalTab}
          target={deepLink ?? undefined}
          compactView={compactView}
          setCompactView={setCompactView}
          onPendingCountMaybeChanged={refreshCount}
        />
      </div>
    </div>
  ) : isNotifications ? (
    // Same single-block shell as 账号信息 / 通用: one padded pane with a centered
    // 720px column holding title, search row and list together.
    <div className="flex min-h-0 flex-1 flex-col px-5 pb-3 pt-4">
      <div className="mx-auto flex min-h-0 w-full max-w-[720px] flex-1 flex-col">
        <h2 className={cn("hidden shrink-0 pb-3 md:block", paneTitleClass)}>{sectionTitle}</h2>
        <NotificationPane
          open
          onOpenApprovalCenter={(approvalTarget) => {
            setDeepLink({ taskId: approvalTarget.taskId, instanceId: approvalTarget.instanceId });
            setCompactView("detail");
            navigate(`/settings/${approvalTarget.tab === "my_requests" ? "my-requests" : "my-tasks"}`, {
              replace: true,
            });
          }}
          onUnreadMaybeChanged={refreshCount}
        />
      </div>
    </div>
  ) : (
    <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-4">
      <div className="mx-auto w-full max-w-[720px]">
        <h2 className={cn("hidden pb-3 md:block", paneTitleClass)}>{sectionTitle}</h2>
        {section === "account" && <AccountPane />}
        {section === "general" && <GeneralSection />}
      </div>
    </div>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-white">
      {/* Mobile top bar — hamburger reveals the system menu, same as channel/knowledge pages. */}
      {isMobile ? (
        <div className="sticky top-0 z-[50] w-full shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
          <div className="relative flex h-11 min-h-11 w-full flex-row items-center justify-between px-4">
            <button
              type="button"
              aria-label={localize("com_nav_open_sidebar")}
              onClick={() => setSystemMenuOpen(true)}
              className="inline-flex size-5 shrink-0 items-center justify-center text-text-1"
            >
              <Outlined.SidebarMenu className="size-5" />
            </button>
            <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 truncate text-[16px] font-medium leading-6 text-text-1">
              {localize("com_nav_settings")}
            </span>
            <div className="min-w-0 flex-1" aria-hidden />
          </div>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* Desktop: vertical nav on the left — padding mirrors the home (Seedmind) sidebar:
            panel pt-4 px-3 pb-3, title pl-3 leading-8, 12px gap before the item groups.
            Group captions reuse the home sidebar's date-label style. */}
        <nav className="hidden w-[200px] shrink-0 flex-col border-r border-fill-2 px-3 pb-3 pt-4 md:flex">
          <div className="flex items-center gap-1 pl-2">
            {/* Leaves settings entirely: section switches replace their history entry, so
                one step back lands on the page the user opened settings from. A direct
                visit (no prior entry in this tab) falls back to home. */}
            <button
              type="button"
              aria-label={localize("com_ui_go_back")}
              onClick={() => {
                if ((window.history.state?.idx ?? 0) > 0) navigate(-1);
                else navigate("/");
              }}
              className="flex size-6 shrink-0 items-center justify-center rounded-md text-text-2 transition-colors hover:bg-fill-2 hover:text-text-1"
            >
              <Outlined.ArrowLeft className="size-4" />
            </button>
            <span aria-hidden className="h-3.5 w-px shrink-0 bg-border-base" />
            <h1 className="ml-1 text-base font-semibold leading-8 text-text-1">
              {localize("com_nav_settings")}
            </h1>
          </div>
          <div className="flex flex-col pt-3">
            {SETTINGS_NAV_GROUPS.map((group, groupIdx) => (
              <div key={group.labelKey} className="flex flex-col gap-1">
                <div
                  className={cn(
                    "mb-1 pl-3 text-[12px] text-text-3",
                    groupIdx === 0 ? "pt-0" : "pt-4",
                  )}
                >
                  {localize(group.labelKey)}
                </div>
                {group.items.map((item) => {
                  const ItemIcon = item.icon;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      className={cn(
                        // 32px row: 22px content line + 5px vertical padding, matching the home sidebar rows.
                        "flex items-center justify-between gap-2 rounded-lg px-3 py-[5px] text-left text-[14px] leading-[22px] transition-colors",
                        section === item.key
                          ? "bg-fill-2 font-medium text-text-1"
                          : "text-text-2 hover:bg-fill-1",
                      )}
                      onClick={() => goToSection(item.key)}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <ItemIcon className="size-4 shrink-0" />
                        <span className="truncate">{localize(item.labelKey)}</span>
                      </span>
                      <NavCountBadge count={navBadge(item.key)} />
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </nav>

        {/* Mobile: horizontal tabs (hidden while an approval detail is open full-screen) */}
        <nav
          className={cn(
            "flex shrink-0 gap-1 overflow-x-auto border-b border-fill-2 px-4 pb-2 pt-1 md:hidden",
            isApproval && compactView === "detail" && "hidden",
          )}
        >
          {SETTINGS_NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={cn(
                "flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-[13px] transition-colors",
                section === item.key ? "bg-fill-2 font-medium text-text-1" : "text-text-3",
              )}
              onClick={() => goToSection(item.key)}
            >
              {localize(item.labelKey)}
              <NavCountBadge count={navBadge(item.key)} />
            </button>
          ))}
        </nav>

        <div className="flex min-h-0 flex-1 flex-col">{content}</div>
      </div>
    </div>
  );
}
