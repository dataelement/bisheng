import { Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import type { MouseEvent, ReactElement, ReactNode } from 'react';
import { cloneElement, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { ActionMenuContent, ActionMenuDivider, ActionMenuItem } from '~/components/ActionMenu';
import { useStartNewChat } from '~/components/Nav/NewChat';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { useLocalize } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { cn } from '~/utils';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';
import { UserPopMenu } from '../UserPopMenu';
import { useWorkbenchNavLinks } from '../useWorkbenchNavLinks';
import { SidebarConversationList } from './SidebarConversationList';
import { SidebarCustomizeDialog } from './SidebarCustomizeDialog';
import { SidebarProjects } from './SidebarProjects';
import { useSidebarPrefs } from './sidebarPrefs';
import { splitSidebarEntries, useSidebarEntries } from './useSidebarEntries';

/** Shown next to the logo when the admin has not configured a 首页 display name. */
const DEFAULT_BRAND_NAME = 'BISHENG';

const BRAND_LINK = 'flex h-8 min-w-0 items-center gap-2.5';

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
 *
 * The module area lists the modules the account may open — what the user HAS — then 广场,
 * what they can discover across all of them. The nav shows at most four rows, 新建对话
 * included; the rest, and the entries the user hid in 管理侧边栏, are reached through 更多.
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
  const navigate = useNavigate();
  const { links, showAdminEntry } = useWorkbenchNavLinks();
  const allEntries = useSidebarEntries();
  const prefs = useSidebarPrefs();
  const startNewChat = useStartNewChat();
  const [customizeOpen, setCustomizeOpen] = useState(false);

  const homeLink = links.find((link) => link.section === 'home');
  const { shown: entries, more: moreEntries } = splitSidebarEntries(allEntries, prefs, homeLink !== undefined);
  const moreActive = moreEntries.some((entry) => entry.active);
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
      <div className="flex h-8 w-full shrink-0 items-center px-2">
        {homeLink ? (
          <NavLink
            to={homeLink.to}
            onClick={handleSamePathClick(homeLink.to)}
            aria-label={localize('com_workbench_sidebar.home')}
            className={BRAND_LINK}
          >
            {brand}
          </NavLink>
        ) : (
          <div className={BRAND_LINK}>{brand}</div>
        )}
      </div>

      <nav className="flex w-full shrink-0 flex-col gap-1 pb-4">
        {homeLink && (
          <SidebarNavRow
            to={homeGranted ? '/c/new' : homeLink.to}
            icon={<Outlined.MessagePlus />}
            label={localize('com_nav_start_new_chat')}
            onClick={handleNewChat}
          />
        )}
        {entries.map((entry) => (
          <SidebarNavRow
            key={entry.id}
            to={entry.to}
            icon={entry.icon}
            label={entry.label}
            active={entry.active}
            onClick={handleSamePathClick(entry.to)}
          />
        ))}
        {/* The area's last row: 更多 while something is tucked away (管理侧边栏 is its last
            item), else 管理侧边栏 itself. */}
        {moreEntries.length > 0 ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(NAV_ROW, 'data-[state=open]:bg-fill-1', moreActive && 'bg-fill-2 hover:bg-fill-2')}
              >
                <Outlined.More className="size-4 shrink-0" />
                <span className="min-w-0 flex-1 truncate py-px">{localize('com_workbench_sidebar.more')}</span>
              </button>
            </DropdownMenuTrigger>
            <ActionMenuContent align="start" width={216}>
              {moreEntries.map((entry) => (
                <ActionMenuItem
                  key={entry.id}
                  icon={entry.icon}
                  label={entry.label}
                  onSelect={() => {
                    if (entry.to !== pathname) navigate(entry.to);
                  }}
                />
              ))}
              {/* A hairline like the sidebar's own rules — the 1px divider reads too heavy
                  in this short menu. */}
              <ActionMenuDivider hairline />
              <ActionMenuItem
                icon={<Outlined.Setting />}
                label={localize('com_workbench_sidebar.customize')}
                onSelect={() => setCustomizeOpen(true)}
              />
            </ActionMenuContent>
          </DropdownMenu>
        ) : allEntries.length > 0 ? (
          <button type="button" onClick={() => setCustomizeOpen(true)} className={NAV_ROW}>
            <Outlined.Setting className="size-4 shrink-0" />
            <span className="min-w-0 flex-1 truncate py-px">{localize('com_workbench_sidebar.customize')}</span>
          </button>
        ) : null}
      </nav>

      {homeLink && homeGranted ? (
        <SidebarConversationList leading={<SidebarProjects />} />
      ) : (
        <div className="min-h-0 flex-1" />
      )}

      <div className="h-px w-full shrink-0 bg-border-base" />
      {/* Two controls, one row chrome: both 32px tall with the nav rows' 8px radius and
          fill-1 hover — the account button stretches, the admin link is the 32px square. */}
      <div className="flex w-full shrink-0 items-center justify-between gap-1">
        <UserPopMenu variant="sidebar" />
        {showAdminEntry && (
          <Tooltip content={localize('com_nav_admin_panel')}>
            <a
              href={getPlatformAdminPanelUrl()}
              target="_blank"
              rel="noreferrer"
              aria-label={localize('com_nav_admin_panel')}
              className="flex size-8 shrink-0 items-center justify-center rounded-lg text-text-1 outline-none transition-colors hover:bg-fill-1 focus-visible:bg-fill-1"
            >
              <Outlined.DeviceDesktopExchange className="size-4" />
            </a>
          </Tooltip>
        )}
      </div>
      <SidebarCustomizeDialog open={customizeOpen} onOpenChange={setCustomizeOpen} />
    </aside>
  );
}
