import type { Capability } from '~/api/capabilities';
type Translate = (key: string, options?: { defaultValue: string }) => string;
type SearchableCapability = Capability & { searchText?: string };

/** Resolve display copy once so the list, details and search share the same language. */
export function localizeCapability(item: Capability, translate: Translate): SearchableCapability {
  const trialName = item.trial
    ? translate(`com_capability_center.scenario_${item.trial.scenario}`, { defaultValue: item.name })
    : item.name;
  const builtin = item.kind === 'builtin';
  const name = builtin && item.tool_key
    ? translate(`tool:tools.${item.tool_key}.name`, { defaultValue: trialName })
    : trialName;
  const description = builtin && item.tool_key
    ? translate(`tool:tools.${item.tool_key}.desc`, { defaultValue: item.description })
    : item.description;
  const provider = builtin
    ? translate(`tool:categories.${item.provider}.name`, { defaultValue: item.provider })
    : item.provider;
  return {
    ...item, name, description, provider,
    searchText: [item.name, item.description, item.provider, item.tool_key].join(' '),
  };
}

export type CapabilityTab = 'all' | 'skill' | 'tool';
export const CAPABILITY_TABS: CapabilityTab[] = ['all', 'skill', 'tool'];
export function filterCapabilities(items: SearchableCapability[], tab: CapabilityTab, query: string, readyOnly: boolean) {
  const keyword = query.trim().toLocaleLowerCase();
  return items.filter(item => (tab === 'all' || (tab === 'tool' ? item.kind !== 'skill' : item.kind === 'skill')) && (!readyOnly || item.ready)
    && `${item.name} ${item.description} ${item.provider} ${item.invocation_name} ${item.searchText ?? ''}`.toLocaleLowerCase().includes(keyword));
}
export function capabilityCounts(items: Capability[]) {
  return Object.fromEntries(CAPABILITY_TABS.map(tab => [tab, items.filter(item => tab === 'all' || (tab === 'tool' ? item.kind !== 'skill' : item.kind === 'skill')).length]));
}
