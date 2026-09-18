import { Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import type { MouseEvent, ReactElement, ReactNode } from 'react';
import { cloneElement } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useStartNewChat } from '~/components/Nav/NewChat';
import { useLocalize } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { cn } from '~/utils';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';
import { UserPopMenu } from '../UserPopMenu';
import type { WorkbenchNavLink, WorkbenchNavSection } from '../useWorkbenchNavLinks';
import { useWorkbenchNavLinks } from '../useWorkbenchNavLinks';
import { SidebarConversationList } from './SidebarConversationList';
import { SidebarProjectsPlaceholder } from './SidebarProjectsPlaceholder';

/** Shown next to the logo when the admin has not configured a 首页 display name. */
const DEFAULT_BRAND_NAME = 'BISHENG';

/** Module order in the design (Figma 13139:111436); 首页 is the 新建对话 row above them. */
const MODULE_ORDER: WorkbenchNavSection[] = ['knowledge', 'apps', 'channel', 'skills'];

const BRAND_ROW = 'flex h-8 max-w-full shrink-0 items-center gap-2.5 self-start px-2';

const NAV_ROW = 'flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-body text-text-1 transition-colors hover:bg-fill-1';

interface SidebarNavRowProps {
  to: string;
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
}

function SidebarNavRow({ to, icon, label, active = false, onClick }: SidebarNavRowProps) {
  return (
    <NavLink to={to} onClick={onClick} className={cn(NAV_ROW, active && 'bg-fill-2 hover:bg-fill-2')}>
      {cloneElement(icon as ReactElement, { className: 'size-4 shrink-0' })}
      <span className="min-w-0 flex-1 truncate py-px">{label}</span>
    </NavLink>
  );
}

/**
 * Desktop workbench sidebar (Figma 13139:111432): brand row, module entries, 项目,
 * the conversation list and the account row, present on every workbench page.
 * Mobile keeps its own rail / drawers — see MainLayout.
 */
interface WorkbenchSidebarProps {
  /** Keep it mounted but out of layout (设置 swaps its own nav into this slot), so the
   *  conversation list keeps its loaded pages and the 项目 folders their open state. */
  hidden?: boolean;
}

export function WorkbenchSidebar({ hidden = false }: WorkbenchSidebarProps) {
  const localize = useLocalize();
  const { pathname } = useLocation();
  const { data: bsConfig } = useGetBsConfig();
  const { links, showAdminEntry } = useWorkbenchNavLinks();
  const startNewChat = useStartNewChat();

  const homeLink = links.find((link) => link.section === 'home');
  const moduleLinks = MODULE_ORDER.map((section) => links.find((link) => link.section === section)).filter(
    (link): link is WorkbenchNavLink => link !== undefined,
  );
  const brandName = bsConfig?.homeMenuDisplayName?.trim() || DEFAULT_BRAND_NAME;
  const logoSrc = bsConfig?.sidebarIcon?.image ? __APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image : '';

  // A granted 首页 starts a fresh chat; without the grant the link target is the
  // menu-unavailable placeholder and must navigate normally.
  const homeGranted = homeLink?.to.startsWith('/menu-unavailable') === false;
  const handleNewChat = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!homeGranted || event.button !== 0 || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    startNewChat();
  };

  // Re-navigating to the path we are already on still mints a fresh location.key
  // and re-runs every effect keyed on it, for nothing the user can see.
  const handleSamePathClick = (to: string) => (event: MouseEvent<HTMLAnchorElement>) => {
    if (to === pathname) event.preventDefault();
  };

  const brand = (
    <>
      {logoSrc ? <img src={logoSrc} className="size-6 shrink-0 object-contain" alt="" /> : null}
      <span className="truncate text-h4 font-semibold text-text-1">{brandName}</span>
    </>
  );

  return (
    <aside
      className={cn(
        'h-[100dvh] w-[240px] shrink-0 flex-col gap-3 overflow-hidden border-r-[0.5px] border-border-base bg-white px-3 pb-3 pt-5',
        hidden ? 'hidden' : 'flex',
      )}
    >
      {homeLink ? (
        <NavLink
          to={homeLink.to}
          onClick={handleSamePathClick(homeLink.to)}
          aria-label={localize('com_workbench_sidebar.home')}
          className={BRAND_ROW}
        >
          {brand}
        </NavLink>
      ) : (
        <div className={BRAND_ROW}>{brand}</div>
      )}

      <nav className="flex w-full shrink-0 flex-col gap-1 pb-4">
        {homeLink && (
          <SidebarNavRow
            to={homeGranted ? '/c/new' : homeLink.to}
            icon={<Outlined.MessagePlus />}
            label={localize('com_nav_start_new_chat')}
            onClick={handleNewChat}
          />
        )}
        {moduleLinks.map((link) => (
          <SidebarNavRow
            key={link.section}
            to={link.to}
            icon={link.icon}
            label={link.label}
            active={link.isActive}
            onClick={handleSamePathClick(link.to)}
          />
        ))}
      </nav>

      {homeLink && homeGranted ? (
        <SidebarConversationList leading={<SidebarProjectsPlaceholder />} />
      ) : (
        <div className="min-h-0 flex-1" />
      )}

      <div className="h-px w-full shrink-0 bg-border-base" />
      <div className="flex w-full shrink-0 items-center justify-between gap-2 rounded-lg px-2 py-1">
        <UserPopMenu variant="sidebar" />
        {showAdminEntry && (
          <Tooltip content={localize('com_nav_admin_panel')}>
            <a
              href={getPlatformAdminPanelUrl()}
              target="_blank"
              rel="noreferrer"
              aria-label={localize('com_nav_admin_panel')}
              className="flex size-6 shrink-0 items-center justify-center rounded-md text-text-1 transition-colors hover:bg-fill-2"
            >
              <Outlined.DeviceDesktopExchange className="size-4" />
            </a>
          </Tooltip>
        )}
      </div>
    </aside>
  );
}
