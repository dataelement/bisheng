import { Outlined } from 'bisheng-icons';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import { squarePath } from '~/pages/square/squarePaths';
import { useSquareTypes } from '~/pages/square/useSquareTypes';
import type { WorkbenchNavSection } from '../useWorkbenchNavLinks';
import { useWorkbenchNavLinks } from '../useWorkbenchNavLinks';
import type { SidebarEntryId, SidebarPrefs } from './sidebarPrefs';
import { useSidebarPrefs } from './sidebarPrefs';

export interface SidebarEntry {
  id: SidebarEntryId;
  to: string;
  icon: ReactNode;
  label: string;
  active: boolean;
}

/** Default row order of the module area; 首页 is the 新建对话 row above it. */
const MODULE_ORDER: Exclude<WorkbenchNavSection, 'home'>[] = ['knowledge', 'channel', 'apps', 'skills'];

/** The nav shows at most this many rows — 新建对话 counts as one; the rest go under 更多. */
const MAX_VISIBLE_ROWS = 4;

/**
 * Splits the entries into the rows the nav shows and what 更多 holds: first the entries
 * the user kept, in order, up to the row cap (新建对话 takes one of the rows when the
 * account has it); whatever is left — over the cap, or hidden by the user — goes to 更多.
 */
export function splitSidebarEntries(entries: SidebarEntry[], prefs: SidebarPrefs, hasNewChatRow: boolean) {
  const shown = entries
    .filter((entry) => !prefs.hidden.includes(entry.id))
    .slice(0, MAX_VISIBLE_ROWS - (hasNewChatRow ? 1 : 0));
  return { shown, more: entries.filter((entry) => !shown.includes(entry)) };
}

/** Stable sort by the user's order: entries they never placed keep their relative order, at the end. */
export function orderSidebarEntries(entries: SidebarEntry[], order: SidebarEntryId[]): SidebarEntry[] {
  const rank = (id: SidebarEntryId) => (order.includes(id) ? order.indexOf(id) : order.length);
  return [...entries].sort((left, right) => rank(left.id) - rank(right.id));
}

/**
 * Every entry the desktop sidebar's module area can hold for this account, in the user's
 * order (default: the modules it may open — what the user HAS — then 广场, what they can
 * discover across all of them). Shared by the sidebar and 管理侧边栏.
 */
export function useSidebarEntries(): SidebarEntry[] {
  const localize = useLocalize();
  const { pathname } = useLocation();
  const { links } = useWorkbenchNavLinks();
  const hasSquare = useSquareTypes().length > 0;
  const { order } = useSidebarPrefs();

  const entries = MODULE_ORDER.flatMap((section): SidebarEntry[] => {
    const link = links.find((item) => item.section === section);
    return link ? [{ id: section, to: link.to, icon: link.icon, label: link.label, active: link.isActive }] : [];
  });
  if (hasSquare) {
    entries.push({
      id: 'square',
      to: squarePath,
      icon: <Outlined.Binoculars />,
      label: localize('com_workbench_sidebar.square'),
      active: pathname.startsWith(squarePath),
    });
  }
  const sorted = orderSidebarEntries(entries, order);
  const home = links.find(link => link.section === 'home');
  if (home && !home.to.startsWith('/menu-unavailable')) sorted.unshift({
    id: 'capabilities', to: '/capabilities', icon: <Outlined.Application />,
    label: localize('com_capability_center.title'), active: pathname.startsWith('/capabilities'),
  });
  return sorted;
}
