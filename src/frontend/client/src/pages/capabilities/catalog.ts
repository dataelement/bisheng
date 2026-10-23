import type { Capability } from '~/api/capabilities';
export type CapabilityTab = 'all' | 'skill' | 'tool';
export const CAPABILITY_TABS: CapabilityTab[] = ['all', 'skill', 'tool'];
export function filterCapabilities(items: Capability[], tab: CapabilityTab, query: string, readyOnly: boolean) {
  const keyword = query.trim().toLocaleLowerCase();
  return items.filter(item => (tab === 'all' || (tab === 'tool' ? item.kind !== 'skill' : item.kind === 'skill')) && (!readyOnly || item.ready)
    && `${item.name} ${item.description} ${item.provider} ${item.invocation_name}`.toLocaleLowerCase().includes(keyword));
}
export function capabilityCounts(items: Capability[]) {
  return Object.fromEntries(CAPABILITY_TABS.map(tab => [tab, items.filter(item => tab === 'all' || (tab === 'tool' ? item.kind !== 'skill' : item.kind === 'skill')).length]));
}
