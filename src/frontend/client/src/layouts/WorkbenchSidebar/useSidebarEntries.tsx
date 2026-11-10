import { Outlined } from 'bisheng-icons';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import { squarePath } from '~/pages/square/squarePaths';
import { useSquareTypes } from '~/pages/square/useSquareTypes';
import type { WorkbenchNavSection } from '../useWorkbenchNavLinks';
import { useWorkbenchNavLinks } from '../useWorkbenchNavLinks';

type SidebarEntryId = Exclude<WorkbenchNavSection, 'home'> | 'square' | 'capabilities';

export interface SidebarEntry {
  id: SidebarEntryId;
  to: string;
  icon: ReactNode;
  label: string;
  active: boolean;
}

/** Default row order of the module area; 首页 is the 新建对话 row above it. */
const MODULE_ORDER: Exclude<WorkbenchNavSection, 'home'>[] = ['knowledge', 'channel', 'apps'];

/** The nav shows at most this many rows — 新建对话 counts as one; the rest go under 更多. */
const MAX_VISIBLE_ROWS = 4;

/**
 * Split the fixed entry order at the row cap. The new-chat entry occupies one row
 * when available; every remaining module stays accessible through the overflow menu.
 */
export function splitSidebarEntries(entries: SidebarEntry[], hasNewChatRow: boolean) {
  const limit = MAX_VISIBLE_ROWS - (hasNewChatRow ? 1 : 0);
  return { shown: entries.slice(0, limit), more: entries.slice(limit) };
}

/**
 * Available desktop entries in a fixed order: modules, tools and skills, then the
 * discovery square. The web sidebar and embedded desktop share this same list.
 */
export function useSidebarEntries(): SidebarEntry[] {
  const localize = useLocalize();
  const { pathname } = useLocation();
  const { links } = useWorkbenchNavLinks();
  const hasSquare = useSquareTypes().length > 0;

  const entries = MODULE_ORDER.flatMap((section): SidebarEntry[] => {
    const link = links.find((item) => item.section === section);
    return link ? [{ id: section, to: link.to, icon: link.icon, label: link.label, active: link.isActive }] : [];
  });
  const home = links.find((link) => link.section === 'home');
  if (home && !home.to.startsWith('/menu-unavailable')) {
    entries.push({
      id: 'capabilities',
      to: '/capabilities',
      icon: <Outlined.Newspaper />,
      label: localize('com_capability_center.title'),
      active: pathname.startsWith('/capabilities'),
    });
  }
  if (hasSquare) {
    entries.push({
      id: 'square',
      to: squarePath,
      icon: <Outlined.Binoculars />,
      label: localize('com_workbench_sidebar.square'),
      active: pathname.startsWith(squarePath),
    });
  }
  return entries;
}
