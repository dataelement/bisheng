import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Button, SearchInput, StateView, Switch, Tabs } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { Wrench } from 'lucide-react';
import { getCapabilities, setCapabilityAvailability, type Capability } from '~/api/capabilities';
import { getSkillScope } from '~/api/skillCenter';
import { useAuthContext, useLocalize } from '~/hooks';
import { QueryKeys } from '~/types/chat';
import { MODULE_HOME_BODY, MODULE_HOME_COLUMN, MODULE_HOME_FRAME, MODULE_HOME_SEARCH, MODULE_HOME_TOOLBAR, ModuleHomeHeader } from '~/components/ModuleHome';
import { SkillCenterPane } from '~/pages/skills/SkillCenterPane';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { SkillListSkeleton } from '~/pages/skills/SkillList';
import { CapabilityDetail } from './CapabilityDetail';
import { CAPABILITY_TABS, capabilityCounts, filterCapabilities, localizeCapability } from './catalog';

const ICONS = { skill: Outlined.Skill, builtin: Wrench, api: Wrench, mcp: Wrench };
function CapabilityIcon({ item }: { item: Capability }) {
  const Icon = ICONS[item.kind];
  return <span className="flex size-10 shrink-0 items-center justify-center rounded-lg border-[0.5px] border-border-base bg-white text-text-2"><Icon className="size-[18px]" /></span>;
}
export function CapabilityCenterPage() {
  const { user } = useAuthContext();
  const localize = useLocalize();
  const t = (key: string) => localize(`com_capability_center.${key}`);
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const skillCenter = useSkillCenter();
  const requested = params.get('type');
  const active = CAPABILITY_TABS.find(tab => tab === requested) ?? (['builtin', 'api', 'mcp'].includes(requested ?? '') ? 'tool' : 'all');
  const identity = useQuery(['capability-center', 'scope', user?.id], () => getSkillScope(String(user?.id)), { enabled: !!user?.id, staleTime: 0, retry: false });
  const catalog = useQuery(['capability-center', identity.data], getCapabilities, { enabled: !!identity.data && !identity.isError, staleTime: 0, refetchOnWindowFocus: true });
  const queryClient = useQueryClient();
  const availability = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => setCapabilityAvailability(id, enabled),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries(['capability-center']),
        queryClient.invalidateQueries([QueryKeys.bishengConfig]),
      ]);
    },
  });
  // Tool ids whose availability is being saved. Only those switches are busy; a single
  // mutation's `isLoading` / `variables` cannot tell rows apart.
  const [pendingIds, setPendingIds] = useState<ReadonlySet<number>>(() => new Set());
  const [availabilityFailed, setAvailabilityFailed] = useState(false);
  const toggleAvailability = (id: number, enabled: boolean) => {
    setAvailabilityFailed(false);
    setPendingIds(prev => new Set(prev).add(id));
    availability.mutateAsync({ id, enabled })
      .catch(() => setAvailabilityFailed(true))
      .finally(() => setPendingIds(prev => { const next = new Set(prev); next.delete(id); return next; }));
  };
  const items = (catalog.data ?? []).map(item => localizeCapability(item, localize));
  const counts = capabilityCounts(items);
  counts.skill = (skillCenter.platform.data?.length ?? 0) + (skillCenter.personal.data?.length ?? 0);
  counts.all = counts.skill + counts.tool;
  const filtered = filterCapabilities(items, 'tool', search, false);
  const selected = items.find(item => item.id === params.get('capability'));
  const handleSelect = (id?: string) => {
    const next = new URLSearchParams(params);
    setAvailabilityFailed(false);
    if (id) next.set('capability', id); else next.delete('capability');
    setParams(next, { replace: true });
  };
  return <div className={MODULE_HOME_FRAME}>
    <ModuleHomeHeader title={t('title')} mobileTitleInShell>
      <SearchInput className={`${MODULE_HOME_SEARCH} w-full min-w-0 min-[768px]:w-64`} value={search} onChange={event => setSearch(event.target.value)} onClear={() => setSearch('')} placeholder={t('search')} aria-label={t('search')} />
    </ModuleHomeHeader>
    <div className={`${MODULE_HOME_COLUMN} ${MODULE_HOME_TOOLBAR} mt-4 flex min-w-0 shrink-0 flex-wrap items-center justify-between gap-3`}>
      <Tabs className="dsh-home-tabs min-w-0 flex-1 max-[575px]:basis-full" size="large" variant="neutral" activeKey={active} items={CAPABILITY_TABS.map(tab => ({ key: tab, label: t(tab), badge: counts[tab] }))}
        onChange={key => { const next = new URLSearchParams(); next.set('type', key); setParams(next, { replace: true }); }} />
      {active !== 'tool' && <Button className="max-[575px]:w-full" disabled={!identity.data} onClick={() => setUploadOpen(true)}><Outlined.Plus />{localize('com_skill_center_upload')}</Button>}
    </div>
    <main className={`${MODULE_HOME_BODY} scroll-on-scroll flex min-h-0 min-w-0 w-full flex-1 flex-col items-center overflow-y-auto`}>
      <div className={`${MODULE_HOME_COLUMN} flex min-w-0 flex-1 flex-col pb-3 pt-4`}>
        {active !== 'tool' && <SkillCenterPane onSearchClear={() => setSearch('')} search={search} uploadOpen={uploadOpen} onUploadOpenChange={setUploadOpen} extraProvidedCount={active === 'all' ? counts.tool : 0} />}
        {availabilityFailed && <p role="alert" className="text-body-sm text-danger">{t('availability_failed')}</p>}
        {active !== 'skill' && ((identity.isError || catalog.isError) ? <StateView title={t('failed')} description={t('retry_hint')} action={<Button color="default" variant="outlined" onClick={() => { void identity.refetch(); void catalog.refetch(); }}>{t('retry')}</Button>} />
        : (identity.isLoading || catalog.isLoading) ? <SkillListSkeleton />
        : filtered.length ? <ul className="flex min-w-0 w-full flex-col">
          {filtered.map(item => <li key={item.id} className="relative flex min-w-0 w-full items-center gap-4 border-b-[0.5px] border-border-base px-2 py-3 transition-colors hover:bg-fill-1">
            <button type="button" aria-label={item.name} onClick={() => handleSelect(item.id)}
              className="absolute inset-0 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500" />
            <CapabilityIcon item={item} />
            <div className="pointer-events-none min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-1.5"><h3 className="min-w-0 truncate text-body font-medium text-text-1">{item.name}</h3></div>
              <p className="mt-0.5 truncate text-caption text-text-3">{item.provider}<span aria-hidden className="mx-1.5">·</span>{item.description}</p>
            </div>
            <Switch size="small" className="relative z-[1] shrink-0" checked={item.availability_enabled === true}
              loading={pendingIds.has(item.resource_id)}
              disabled={pendingIds.has(item.resource_id)}
              aria-label={`${t('tool_enabled_setting')}: ${item.name}`}
              onCheckedChange={enabled => toggleAvailability(item.resource_id, enabled)} />
          </li>)}
        </ul> : <StateView title={t('empty')} />)}
      </div>
    </main>
    {selected && <CapabilityDetail key={selected.id} item={selected} onClose={() => handleSelect()}
      availability={typeof selected.availability_enabled === 'boolean' ? {
        checked: selected.availability_enabled,
        busy: pendingIds.has(selected.resource_id),
        onChange: enabled => toggleAvailability(selected.resource_id, enabled),
      } : undefined} availabilityError={availabilityFailed ? t('availability_failed') : undefined} />}
  </div>;
}
