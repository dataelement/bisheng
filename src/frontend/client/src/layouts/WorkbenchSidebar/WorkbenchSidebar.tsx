import { Dropdown, DropdownItem } from "@bisheng/ui";
import { Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import type { MouseEvent, MutableRefObject, ReactElement, ReactNode } from 'react';
import { cloneElement, useMemo, useRef, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useStartNewChat } from '~/components/Nav/NewChat';
import { useAuthContext, useLocalize } from '~/hooks';
import { useConversationsInfiniteQuery, useGetBsConfig } from '~/hooks/queries/data-provider';
import { cn } from '~/utils';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';
import { UserPopMenu } from '../UserPopMenu';
import { useWorkbenchNavLinks } from '../useWorkbenchNavLinks';
import { SidebarConversationList } from './SidebarConversationList';
import { SidebarProjects } from './SidebarProjects';
import { splitSidebarEntries, useSidebarEntries } from './useSidebarEntries';
import { WorkbenchSidebarUnderlay } from './WorkbenchSidebarUnderlay';
import './workbench-navigation.css';

/** Shown next to the logo when the admin has not configured a 首页 display name. */
const DEFAULT_BRAND_NAME = 'BISHENG';

const BRAND_LINK = 'flex h-8 min-w-0 items-center gap-2.5';

const NAV_ROW = 'flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-body text-text-1 transition-colors hover:bg-fill-1 coarse-pointer:min-h-11';
const noop = () => undefined;

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
 * Workbench sidebar (Figma 13139:111432): brand row, module entries, projects,
 * the conversation list and the account row, present on every workbench page.
 * Narrow screens reveal the same content underneath the translated page.
 *
 * The module area lists the modules the account may open — what the user HAS — then 广场,
 * what they can discover across all of them. The nav shows at most four rows, 新建对话
 * included; the remaining entries are reached through the overflow menu.
 */
interface WorkbenchSidebarProps {
  /** Keep it mounted but out of layout (设置 swaps its own nav into this slot), so the
   *  conversation list keeps its loaded pages and the 项目 folders their open state. */
  hidden?: boolean;
  mobile?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  triggerRef?: MutableRefObject<HTMLElement | null>;
}

export function WorkbenchSidebar({ hidden = false, mobile = false, open = false, onOpenChange = noop, triggerRef: externalTriggerRef }: WorkbenchSidebarProps) {
  const localize = useLocalize();
  const { isAuthenticated } = useAuthContext();
  const { pathname } = useLocation();
  const { data: bsConfig } = useGetBsConfig();
  const navigate = useNavigate();
  const { links, showAdminEntry } = useWorkbenchNavLinks();
  const allEntries = useSidebarEntries();
  const startNewChat = useStartNewChat();
  const [openProjectIds, setOpenProjectIds] = useState<string[]>([]);
  const scrollPosition = useRef(0);
  const fallbackTriggerRef = useRef<HTMLElement | null>(null);
  const triggerRef = externalTriggerRef ?? fallbackTriggerRef;

  const homeLink = links.find((link) => link.section === 'home');
  const { shown: entries, more: moreEntries } = splitSidebarEntries(allEntries, homeLink !== undefined);
  const moreActive = moreEntries.some((entry) => entry.active);
  const brandName = bsConfig?.homeMenuDisplayName?.trim() || DEFAULT_BRAND_NAME;
  const logoSrc = bsConfig?.sidebarIcon?.image ? __APP_ENV__.BASE_URL + bsConfig.sidebarIcon.image : '';

  // A granted 首页 starts a fresh chat; without the grant the link target is the
  // menu-unavailable placeholder and must navigate normally.
  const homeGranted = homeLink?.to.startsWith('/menu-unavailable') === false;
  // Keep the query subscribed even while the narrow-screen content is unmounted.
  const conversationsQuery = useConversationsInfiniteQuery(
    { pageNumber: '1', isArchived: false },
    { enabled: isAuthenticated && homeGranted },
  );
  const conversations = useMemo(
    () => conversationsQuery.data?.pages.flatMap((page) => page.conversations).filter((item) => item != null) ?? [],
    [conversationsQuery.data],
  );
  const handleNavigate = () => {
    if (!mobile) return;
    // Navigation owns the next page's focus; do not restore an obsolete trigger.
    triggerRef.current = null;
    onOpenChange(false);
  };
  const handleNewChat = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!homeGranted || event.button !== 0 || event.ctrlKey || event.metaKey) return;
    event.preventDefault();
    startNewChat();
    handleNavigate();
  };

  // Re-navigating to the path we are already on still mints a fresh location.key
  // and re-runs every effect keyed on it, for nothing the user can see.
  const handleSamePathClick = (to: string) => (event: MouseEvent<HTMLAnchorElement>) => {
    if (to === pathname) event.preventDefault();
    handleNavigate();
  };

  const brand = (
    <>
      {logoSrc ? <img src={logoSrc} className="workbench-sidebar-logo size-6 shrink-0 object-contain" alt="" /> : null}
      <span className="workbench-sidebar-brand truncate text-h4 font-semibold text-text-1">{brandName}</span>
    </>
  );

  const sidebar = (
    <aside
      data-workbench-sidebar
      className={cn(
        'h-[100dvh] w-[240px] shrink-0 flex-col gap-3 overflow-hidden border-r-[0.5px] border-border-base bg-white px-3 pb-3',
        hidden ? 'hidden' : 'flex',
        mobile ? 'workbench-sidebar-mobile border-0' : 'pt-5',
      )}
    >
      <div className="flex h-8 w-full shrink-0 items-center justify-between gap-1 px-2 coarse-pointer:min-h-11">
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
        {moreEntries.length > 0 && (
          <Dropdown  align="start" menu={<>
              {moreEntries.map((entry) => (
                <DropdownItem
                  key={entry.id}
                  icon={entry.icon}

                  onSelect={() => {
                    if (entry.to !== pathname) navigate(entry.to);
                    handleNavigate();
                  }}
                >{entry.label}</DropdownItem>
              ))}
             </>}>
              <button
                type="button"
                className={cn(NAV_ROW, 'data-[state=open]:bg-fill-1', moreActive && 'bg-fill-2 hover:bg-fill-2')}
              >
                <Outlined.More className="size-4 shrink-0" />
                <span className="min-w-0 flex-1 truncate py-px">{localize('com_workbench_sidebar.more')}</span>
              </button>
             </Dropdown>
        )}
      </nav>

      {homeLink && homeGranted ? (
        <SidebarConversationList
          query={conversationsQuery}
          scrollPosition={scrollPosition}
          onNavigate={handleNavigate}
          leading={<SidebarProjects conversations={conversations} openIds={openProjectIds}
            onOpenIdsChange={setOpenProjectIds} onNavigate={handleNavigate} />}
        />
      ) : (
        <div className="min-h-0 flex-1" />
      )}

      <div className="h-px w-full shrink-0 bg-border-base" />
      {/* Two controls, one row chrome: both 32px tall with the nav rows' 8px radius and
          fill-1 hover — the account button stretches, the admin link is the 32px square. */}
      <div className="flex w-full shrink-0 items-center justify-between gap-1">
        <UserPopMenu variant="sidebar" onNavigate={handleNavigate} />
        {showAdminEntry && (
          <Tooltip content={localize('com_nav_admin_panel')}>
            <a
              href={getPlatformAdminPanelUrl()}
              target="_blank"
              rel="noreferrer"
              aria-label={localize('com_nav_admin_panel')}
              onClick={handleNavigate}
              className="flex size-8 shrink-0 items-center justify-center rounded-lg text-text-1 outline-none transition-colors hover:bg-fill-1 focus-visible:bg-fill-1"
            >
              <Outlined.DeviceDesktopExchange className="size-4" />
            </a>
          </Tooltip>
        )}
      </div>
    </aside>
  );

  return mobile ? (
    <WorkbenchSidebarUnderlay open={open} onOpenChange={onOpenChange} triggerRef={triggerRef}
      label={brandName} closeLabel={localize('com_nav_close_sidebar')}>
      {sidebar}
    </WorkbenchSidebarUnderlay>
  ) : sidebar;
}
