import { Outlined } from 'bisheng-icons';
import type { ReactNode } from 'react';
import { useLocalize } from '~/hooks';
import type { WorkbenchHubId, WorkbenchNavLink, WorkbenchNavSection } from './useWorkbenchNavLinks';
import { useWorkbenchNavLinks } from './useWorkbenchNavLinks';

export interface WorkbenchHub {
  id: WorkbenchHubId;
  label: string;
  icon: ReactNode;
  /** Granted modules of this hub, in tab order. Never empty. */
  modules: WorkbenchNavLink[];
  /** Module the hub entry opens: the one last visited, else the first. */
  landing: WorkbenchNavLink;
  /** The module the user is in right now, when it belongs to this hub. */
  activeModule?: WorkbenchNavLink;
}

const HUB_DEFS: { id: WorkbenchHubId; labelKey: string; icon: ReactNode; sections: WorkbenchNavSection[] }[] = [
  {
    id: 'knowledge',
    labelKey: 'com_workbench_sidebar.hub_knowledge',
    icon: <Outlined.Bulb />,
    sections: ['knowledge', 'channel'],
  },
  {
    id: 'ability',
    labelKey: 'com_workbench_sidebar.hub_ability',
    icon: <Outlined.Binoculars />,
    sections: ['apps', 'skills'],
  },
];

/** Last module visited per hub — module-level like `lastSectionPaths`, reset on reload. */
const lastHubSection: Partial<Record<WorkbenchHubId, WorkbenchNavSection>> = {};

/**
 * The desktop sidebar's hubs, built from the permission-filtered module links so a hub
 * only ever holds modules the user may open; a hub with none is dropped. Shared by the
 * sidebar, its customize dialog and the module homes' type switcher.
 */
export function useWorkbenchHubs(): WorkbenchHub[] {
  const localize = useLocalize();
  const { links } = useWorkbenchNavLinks();

  return HUB_DEFS.flatMap((def) => {
    const modules = def.sections
      .map((section) => links.find((link) => link.section === section))
      .filter((link): link is WorkbenchNavLink => link !== undefined);
    if (modules.length === 0) return [];
    const activeModule = modules.find((link) => link.isActive);
    if (activeModule) lastHubSection[def.id] = activeModule.section;
    const landing = modules.find((link) => link.section === lastHubSection[def.id]) ?? modules[0];
    return [{ id: def.id, label: localize(def.labelKey), icon: def.icon, modules, landing, activeModule }];
  });
}
