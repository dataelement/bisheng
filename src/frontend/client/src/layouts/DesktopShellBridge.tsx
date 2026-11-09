import { useEffect } from "react";
import { useGetBsConfig } from "~/hooks/queries/data-provider";
import { useLocalize } from "~/hooks";
import { workbenchBranding } from "~/components/Chat/workbenchBranding";
import { useLocation, useNavigate } from "react-router-dom";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import { readDesktopPresentation } from "~/utils/clientEnvironment";
import { useDesktopNavigation } from "~/components/Chat/useDesktopNavigation";
import { useDesktopAppearance } from "~/components/Chat/useDesktopAppearance";
import { useWorkbenchNavLinks } from "./useWorkbenchNavLinks";
import {
  splitSidebarEntries,
  useSidebarEntries,
} from "./WorkbenchSidebar/useSidebarEntries";
import { usePersonalTokenEnabled } from "~/hooks/useVersionManagementEnabled";
import { useDesktopLocale } from "./useDesktopLocale";
import { useChatProjectSync } from "~/hooks/useChatProjects";
import { useProjectMigration } from "~/hooks/useProjectMigration";

/** The web app owns grants, labels and ordering; the host owns desktop navigation chrome. */
export function DesktopShellBridge() {
  useChatProjectSync();
  useProjectMigration();
  const navigate = useNavigate();
  useEffect(() => {
    const recover = (event: Event) => {
      const value: unknown = (event as CustomEvent<{ chatId?: unknown }>).detail?.chatId;
      if (typeof value === 'string' && /^[A-Za-z0-9_-]{1,255}$/.test(value)) navigate(`/c/${value}`);
    };
    window.addEventListener('bisheng:project-conversation-recovered', recover);
    return () => window.removeEventListener('bisheng:project-conversation-recovered', recover);
  }, [navigate]);
  useDesktopNavigation();
  useDesktopAppearance();
  useDesktopLocale();
  const {
    channel,
    capabilities: { hasNativePresentation },
  } = useClientEnvironment();
  const { pathname, search } = useLocation();
  const { data: bsConfig } = useGetBsConfig();
  const localize = useLocalize();
  const aiAccess = usePersonalTokenEnabled();
  const entries = useSidebarEntries();
  const { links } = useWorkbenchNavLinks();
  const { shown } = splitSidebarEntries(
    entries,
    links.some((link) => link.section === "home"),
  );
  const payload = JSON.stringify({
    settings: { aiAccess },
    entries: entries.map(({ id, to, label, active }) => ({
      id,
      path: to,
      label,
      active,
      primary: shown.some((entry) => entry.id === id),
    })),
    branding: workbenchBranding(bsConfig, localize("dshChat.welcome")),
    homeLabel: links.find((link) => link.section === "home")?.label,
    path: pathname + search,
  });
  useEffect(() => {
    if (channel === "desktop")
      readDesktopPresentation().reportNavigation?.(JSON.parse(payload));
  }, [payload, channel, hasNativePresentation]);
  return null;
}
