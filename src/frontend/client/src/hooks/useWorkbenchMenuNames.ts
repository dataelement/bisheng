import { useEffect } from 'react';
import { useAuthContext } from '~/hooks/AuthContext';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import type { BsConfig } from '~/types/chat/config';
import useLocalize from './useLocalize';

/** Workbench sidebar modules, keyed the same way as the sidebar link sections. */
export type WorkbenchMenuKey = 'home' | 'knowledge' | 'channel' | 'apps';

type CustomMenuNames = Partial<Record<WorkbenchMenuKey, string>>;

function getCustomMenuNames(config: BsConfig): CustomMenuNames {
  return {
    home: config.homeMenuDisplayName?.trim(),
    knowledge: config.knowledge_space?.menu_display_name?.trim(),
    channel: config.subscription?.menu_display_name?.trim(),
    apps: config.appCenterMenuDisplayName?.trim(),
  };
}

function readCachedMenuNames(key: string): CustomMenuNames {
  try {
    const cached = window.localStorage.getItem(key);
    if (!cached) return {};
    const names = JSON.parse(cached) as CustomMenuNames | null;
    return {
      home: typeof names?.home === 'string' ? names.home : undefined,
      knowledge: typeof names?.knowledge === 'string' ? names.knowledge : undefined,
      channel: typeof names?.channel === 'string' ? names.channel : undefined,
      apps: typeof names?.apps === 'string' ? names.apps : undefined,
    };
  } catch {
    return {};
  }
}

/** Save only custom names so that defaults always follow the current UI language. */
export function useWorkbenchMenuNames(): Record<WorkbenchMenuKey, string> {
  const localize = useLocalize();
  const { user } = useAuthContext();
  const { data: bsConfig, isSuccess } = useGetBsConfig();
  const tenantId = user?.tenant_id;
  const cacheKey = tenantId == null ? null : `bs-workbench-menu-names:${tenantId}`;

  useEffect(() => {
    if (!cacheKey || !isSuccess || !bsConfig) return;

    try {
      const names = JSON.stringify(getCustomMenuNames(bsConfig));
      if (window.localStorage.getItem(cacheKey) !== names) {
        window.localStorage.setItem(cacheKey, names);
      }
    } catch {
      // Storage may be disabled or full.
    }
  }, [bsConfig, cacheKey, isSuccess]);

  const names = bsConfig
    ? getCustomMenuNames(bsConfig)
    : cacheKey ? readCachedMenuNames(cacheKey) : {};

  return {
    home: names.home || localize('com_nav_home'),
    knowledge: names.knowledge || localize('com_knowledge.knowledge_space'),
    channel: names.channel || localize('com_ui_channel'),
    apps: names.apps || localize('com_nav_app_center'),
  };
}
