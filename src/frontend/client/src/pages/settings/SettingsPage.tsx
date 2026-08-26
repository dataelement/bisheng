import { Outlined } from "bisheng-icons";
import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
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
  readSettingsRouteState,
  resolveSettingsExitTarget,
  type SettingsRouteState,
} from "./settingsHistory";
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
 * History model differs by layout:
 * - Desktop: sidebar moves REPLACE the entry — settings holds exactly one entry, so
 *   back always leaves settings to wherever the user came from.
 * - Mobile: /settings (no section) is a menu landing; picking a module PUSHES, so
 *   both the top back button and system back pop to the menu first, and backing out
 *   of the menu leaves settings.
 *
 * Ownership stays strict (same as the retired dialog): an approval that still needs
 * handling lives only under 我的审批-待我处理, and 通知 only informs — nothing here
 * decrements the pending count except a real decision.
 */
export default function SettingsPage() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const location = useLocation();
  const isMobile = usePrefersMobileLayout();
  const setSystemMenuOpen = useSetRecoilState(store.mobileSystemMenuOpenState);
  const { section: rawSection } = useParams<{ section?: string }>();
  const { unreadCount, pendingApprovalCount, refreshCount } = useNotificationCount();

  // Compact (<768px) approval master-detail state, owned here so the nav can reset it.
  const [compactView, setCompactView] = useState<"list" | "detail">("list");
  /** Set when a notification jumps into an approval detail. */
  const [deepLink, setDeepLink] = useState<{ taskId?: number | null; instanceId?: number | null } | null>(null);

  /** Mobile-only menu landing: /settings with no section segment. */
  const isMenu = isMobile && rawSection == null;

  /** The entry source is captured once; all navigation inside settings only carries it. */
  const settingsRouteState = readSettingsRouteState(location.state);
  const cameFromMenu = settingsRouteState.fromSettingsMenu === true;

  const section: SettingsPageSection = isSettingsPageSection(rawSection)
    ? rawSection
    : DEFAULT_SETTINGS_SECTION;

  // Section changes can change both counts (decisions, read state) — keep the badges fresh.
  useEffect(() => {
    void refreshCount();
  }, [section, refreshCount]);

  // Leaves settings for the route that opened it. Direct visits fall back to browser
  // history and then home when this is the first entry in the tab.
  const leaveSettings = () => {
    const target = resolveSettingsExitTarget(settingsRouteState, window.history.state?.idx);
    if (target.delta !== undefined) navigate(target.delta);
    else navigate(target.path, { replace: true });
  };

  if (!isMenu && !isSettingsPageSection(rawSection)) {
    // Desktop has no menu screen — /settings and unknown sections land on the default
    // section. Mobile unknown sections land on the menu.
    return (
      <Navigate
        to={isMobile ? "/settings" : `/settings/${DEFAULT_SETTINGS_SECTION}`}
        replace
        state={settingsRouteState}
      />
    );
  }

  // Desktop sidebar/deep-link moves REPLACE the history entry: settings keeps exactly
  // one entry, so 返回 (and the browser's own back) leads to whatever page the user
  // was on before opening settings, never through the sections they browsed here.
  const goToSection = (next: SettingsPageSection) => {
    setCompactView("list");
    setDeepLink(null);
    navigate(`/settings/${next}`, { replace: true, state: settingsRouteState });
  };

  // Mobile menu → module PUSHES (flagged), so back — button or gesture — pops to the menu.
  const openSectionFromMenu = (next: SettingsPageSection) => {
    setCompactView("list");
    setDeepLink(null);
    navigate(`/settings/${next}`, {
      state: { ...settingsRouteState, fromSettingsMenu: true } satisfies SettingsRouteState,
    });
  };

  // Mobile module back → the menu. Pop when the menu pushed this entry; otherwise
  // (deep link, external redirect) swap it for the menu so backing out still leaves.
  const backToMenu = () => {
    if (cameFromMenu && (window.history.state?.idx ?? 0) > 0) navigate(-1);
    else {
      const menuState: SettingsRouteState = settingsRouteState.settingsOrigin
        ? { settingsOrigin: settingsRouteState.settingsOrigin }
        : {};
      navigate("/settings", { replace: true, state: menuState });
    }
  };

  const approvalTab = approvalTabOf(section);
  const isApproval = approvalTab != null;
  const isNotifications = section === "notifications";

  const navBadge = (key: SettingsPageSection) =>
    key === "my-tasks" ? pendingApprovalCount : key === "notifications" ? unreadCount : 0;

  // Mobile menu landing — the grouped nav as a full screen. Rows mirror the desktop
  // sidebar's grouping but at touch size; the hamburger stays here (module screens
  // swap it for a back button).
  if (isMenu) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-white">
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
        <div className="scrollbar-os min-h-0 flex-1 overflow-y-auto px-3 pb-6 pt-1">
          {SETTINGS_NAV_GROUPS.map((group, groupIdx) => (
            <div key={group.labelKey} className="flex flex-col gap-0.5">
              <div
                className={cn(
                  "mb-1 pl-3 text-[13px] text-text-3",
                  groupIdx === 0 ? "pt-2" : "pt-5",
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
                    className="flex h-11 items-center justify-between gap-3 rounded-lg px-3 text-left text-[15px] leading-[22px] text-text-1 transition-colors coarse-pointer:active:bg-fill-2"
                    onClick={() => openSectionFromMenu(item.key)}
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <ItemIcon className="size-5 shrink-0" />
                      <span className="truncate">{localize(item.labelKey)}</span>
                    </span>
                    <NavCountBadge count={navBadge(item.key)} />
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    );
  }

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
            // Replace keeps the module depth flat; carrying state preserves whether
            // the mobile menu pushed this entry (so its back button still pops).
            navigate(`/settings/${approvalTarget.tab === "my_requests" ? "my-requests" : "my-tasks"}`, {
              replace: true,
              state: settingsRouteState,
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
      {/* Mobile module top bar — back leads to the settings menu, title names the module. */}
      {isMobile ? (
        <div className="sticky top-0 z-[50] w-full shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
          <div className="relative flex h-11 min-h-11 w-full flex-row items-center justify-between px-4">
            <button
              type="button"
              aria-label={localize("com_ui_go_back")}
              onClick={backToMenu}
              className="inline-flex size-5 shrink-0 items-center justify-center text-text-1"
            >
              <Outlined.ArrowLeft className="size-5" />
            </button>
            <span className="pointer-events-none absolute left-1/2 max-w-[60%] -translate-x-1/2 truncate text-[16px] font-medium leading-6 text-text-1">
              {sectionTitle}
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
                one step back lands on the page the user opened settings from. */}
            <button
              type="button"
              aria-label={localize("com_ui_go_back")}
              onClick={leaveSettings}
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

        <div className="flex min-h-0 flex-1 flex-col">{content}</div>
      </div>
    </div>
  );
}
