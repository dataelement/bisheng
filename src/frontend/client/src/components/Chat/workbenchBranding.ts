import type { BsConfig } from '~/types/chat';

/** Shared presentation derived from the Build → Workbench settings. */
export function workbenchBranding(config: BsConfig | undefined, defaultWelcome: string) {
  const source = config?.assistantIcon?.image || '/assets/bisheng/logo-mark.svg';
  const base = (__APP_ENV__.BASE_URL || '').replace(/\/$/, '');
  const path = /^https?:\/\//i.test(source) || source.startsWith(`${base}/`)
    ? source : `${base}/${source.replace(/^\//, '')}`;
  return {
    welcomeMessage: config?.welcomeMessage?.trim() || defaultWelcome,
    assistantIcon: { enabled: config?.assistantIcon?.enabled !== false, image: new URL(path, window.location.origin).href },
  };
}
