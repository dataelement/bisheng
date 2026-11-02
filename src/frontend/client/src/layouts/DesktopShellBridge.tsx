import { useEffect } from 'react';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useLocalize } from '~/hooks';
import { workbenchBranding } from '~/components/Chat/workbenchBranding';
import { useLocation } from 'react-router-dom';
import { isDesktopEmbedded } from '~/components/Chat/desktopEmbedding';
import { useDesktopNavigation } from '~/components/Chat/useDesktopNavigation';
import { useDesktopAppearance } from '~/components/Chat/useDesktopAppearance';
import { useWorkbenchNavLinks } from './useWorkbenchNavLinks';
import { splitSidebarEntries, useSidebarEntries } from './WorkbenchSidebar/useSidebarEntries';
import { usePersonalTokenEnabled } from '~/hooks/useVersionManagementEnabled';
import { useSidebarPrefs } from './WorkbenchSidebar/sidebarPrefs';
import { useDesktopLocale } from './useDesktopLocale';

/** The web app owns grants, labels and ordering; the host owns desktop navigation chrome. */
export function DesktopShellBridge() {
  useDesktopNavigation();
  useDesktopAppearance();
  useDesktopLocale();
  const { pathname, search } = useLocation();
  const { data: bsConfig } = useGetBsConfig();
  const localize = useLocalize();
  const aiAccess = usePersonalTokenEnabled();
  const entries = useSidebarEntries();
  const { links } = useWorkbenchNavLinks();
  const prefs = useSidebarPrefs();
  const { shown } = splitSidebarEntries(entries, prefs, links.some(link => link.section === 'home'));
  const payload = JSON.stringify({
    settings: { aiAccess },
    entries: entries.map(({ id, to, label, active }) => ({ id, path: to, label, active, primary: shown.some(entry => entry.id === id) })),
    branding: workbenchBranding(bsConfig, localize('dshChat.welcome')),
    homeLabel: links.find(link => link.section === 'home')?.label,
    path: pathname + search,
  });
  useEffect(() => {
    if (isDesktopEmbedded()) window.dshChatPresentation?.reportNavigation?.(JSON.parse(payload));
  }, [payload]);
  return null;
}
