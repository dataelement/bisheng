import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Button, SearchInput, StateView, Tabs, Tag } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { Cable, Code2, Wrench } from 'lucide-react';
import { getCapabilities, setCapabilityAvailability, type Capability } from '~/api/capabilities';
import { getSkillScope } from '~/api/skillCenter';
import { useAuthContext, useLocalize } from '~/hooks';
import { QueryKeys } from '~/types/chat';
import { MODULE_HOME_COLUMN, MODULE_HOME_FRAME, ModuleHomeHeader } from '~/components/ModuleHome';
import { SkillCenterPane } from '~/pages/skills/SkillCenterPane';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { SkillListSkeleton } from '~/pages/skills/SkillList';
import { CapabilityDetail } from './CapabilityDetail';
import { CAPABILITY_TABS, capabilityCounts, filterCapabilities } from './catalog';

const ICONS = { skill: Outlined.Skill, builtin: Wrench, api: Code2, mcp: Cable };
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
  const active = CAPABILITY_TABS.find(tab => tab === requested) ?? 'all';
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
  const items = catalog.data ?? [];
  const counts = capabilityCounts(items);
  counts.skill = (skillCenter.platform.data?.length ?? 0) + (skillCenter.personal.data?.length ?? 0);
  const filtered = filterCapabilities(items, active, search, false);
  const selected = items.find(item => item.id === params.get('capability'));
  const displayName = (item: Capability) => item.trial ? t(`scenario_${item.trial.scenario}`) : item.name;
  const handleSelect = (id?: string) => {
    const next = new URLSearchParams(params);
    availability.reset();
    if (id) next.set('capability', id); else next.delete('capability');
    setParams(next, { replace: true });
  };
  return <div className={MODULE_HOME_FRAME}>
    <ModuleHomeHeader title={t('title')}>
      <SearchInput className="w-48 min-[576px]:w-64" value={search} onChange={event => setSearch(event.target.value)} onClear={() => setSearch('')} placeholder={t('search')} aria-label={t('search')} />
    </ModuleHomeHeader>
    <div className={`${MODULE_HOME_COLUMN} mt-4 flex shrink-0 items-center justify-between gap-4`}>
      <Tabs className="min-w-0 flex-1" size="large" variant="neutral" activeKey={active} items={CAPABILITY_TABS.map(tab => ({ key: tab, label: t(tab), badge: counts[tab] }))}
        onChange={key => { const next = new URLSearchParams(); next.set('type', key); setParams(next, { replace: true }); }} />
      {active === 'skill' && <Button disabled={!identity.data} onClick={() => setUploadOpen(true)}><Outlined.Plus />{localize('com_skill_center_upload')}</Button>}
    </div>
    <main className="scroll-on-scroll flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
      <div className={`${MODULE_HOME_COLUMN} flex flex-1 flex-col pb-3 pt-4`}>
        {active === 'skill' ? <SkillCenterPane search={search} uploadOpen={uploadOpen} onUploadOpenChange={setUploadOpen} /> : (identity.isError || catalog.isError) ? <StateView title={t('failed')} description={t('retry_hint')} action={<Button color="default" variant="outlined" onClick={() => { void identity.refetch(); void catalog.refetch(); }}>{t('retry')}</Button>} />
        : (identity.isLoading || catalog.isLoading) ? <SkillListSkeleton />
        : filtered.length ? <ul className="flex w-full flex-col">
          {filtered.map(item => <li key={item.id} className="relative flex w-full items-center gap-4 border-b-[0.5px] border-border-base px-2 py-3 transition-colors hover:bg-fill-1">
            <button type="button" aria-label={displayName(item)} onClick={() => handleSelect(item.id)}
              className="absolute inset-0 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500" />
            <CapabilityIcon item={item} />
            <div className="pointer-events-none min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-1.5"><h3 className="min-w-0 truncate text-body font-medium text-text-1">{displayName(item)}</h3><Tag className="shrink-0">{t(item.kind)}</Tag></div>
              <p className="mt-0.5 truncate text-caption text-text-3">{item.provider}<span aria-hidden className="mx-1.5">·</span>{item.description}</p>
            </div>
          </li>)}
        </ul> : <StateView title={t('empty')} />}
      </div>
    </main>
    {selected && <CapabilityDetail key={selected.id} item={selected} onClose={() => handleSelect()}
      webSearch={typeof selected.availability_enabled === 'boolean' ? {
        checked: selected.availability_enabled,
        busy: availability.isLoading,
        onChange: enabled => availability.mutate({ id: selected.resource_id, enabled }),
      } : undefined} availabilityError={availability.isError ? t('availability_failed') : undefined} />}
  </div>;
}
