import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { isDesktopEmbedded } from '~/components/Chat/desktopEmbedding';
import { useDesktopNavigation } from '~/components/Chat/useDesktopNavigation';
import { useDesktopAppearance } from '~/components/Chat/useDesktopAppearance';
import { useWorkbenchNavLinks } from './useWorkbenchNavLinks';
import { splitSidebarEntries, useSidebarEntries } from './WorkbenchSidebar/useSidebarEntries';
import { useSidebarPrefs } from './WorkbenchSidebar/sidebarPrefs';

/** The web app owns grants, labels and ordering; the host owns desktop navigation chrome. */
export function DesktopShellBridge() {
  useDesktopNavigation();
  useDesktopAppearance();
  const { pathname, search } = useLocation();
  const entries = useSidebarEntries();
  const { links } = useWorkbenchNavLinks();
  const prefs = useSidebarPrefs();
  const { shown } = splitSidebarEntries(entries, prefs, links.some(link => link.section === 'home'));
  const payload = JSON.stringify({
    entries: entries.map(({ id, to, label, active }) => ({ id, path: to, label, active, primary: shown.some(entry => entry.id === id) })),
    homeLabel: links.find(link => link.section === 'home')?.label,
    path: pathname + search,
  });
  useEffect(() => {
    if (isDesktopEmbedded()) window.dshChatPresentation?.reportNavigation?.(JSON.parse(payload));
  }, [payload]);
  return null;
}
