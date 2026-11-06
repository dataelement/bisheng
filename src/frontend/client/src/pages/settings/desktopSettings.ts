import { isNativeDesktop } from '~/locales/desktopLocale';

const SECTIONS = ['account', 'desktop-usage', 'ai-access', 'my-tasks', 'my-requests', 'notifications'] as const;
export type DesktopSettingsSection = (typeof SECTIONS)[number];

/** A URL alone cannot activate host-owned settings or expose native capabilities. */
export function readDesktopSettingsSection(section: unknown, search: string): DesktopSettingsSection | undefined {
  if (!isNativeDesktop() || new URLSearchParams(search).get('dshSettings') !== '1') return undefined;
  return SECTIONS.find(value => value === section);
}
