import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { Button, SearchInput, StateView, Tag } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { SkillUploadDialog } from '~/components/Skills/SkillUploadDialog';
import { SkillDetails } from '~/components/Skills/SkillDetails';
import type { CenterSkill, PersonalSkill } from '~/components/Skills/types';

export function SkillCenterPage() {
  const localize = useLocalize();
  const { identity, platform, personal } = useSkillCenter();
  const [search, setSearch] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [target, setTarget] = useState<PersonalSkill>();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get('skill');
  const setSelectedId = (id?: string) => {
    const next = new URLSearchParams(params);
    if (id) next.set('skill', id);
    else next.delete('skill');
    setParams(next, { replace: true });
  };
  const [saved, setSaved] = useState(false);
  const skills = useMemo<CenterSkill[]>(() => [
    ...(platform.data ?? []), ...(personal.data ?? []),
  ].sort((left, right) => left.displayName.localeCompare(right.displayName)), [platform.data, personal.data]);
  const keyword = search.trim().toLocaleLowerCase();
  const filtered = skills.filter((skill) => `${skill.displayName} ${skill.name} ${skill.description}`.toLocaleLowerCase().includes(keyword));
  const selected = skills.find((skill) => skill.id === selectedId);
  const loading = identity.isLoading || platform.isFetching || personal.isFetching;
  const failed = identity.isError || platform.isError || personal.isError;
  const startUpload = () => { setTarget(undefined); setSaved(false); setUploadOpen(true); };
  const retry = () => { void identity.refetch(); void platform.refetch(); void personal.refetch(); };

  return (
    <div className="h-full min-h-0 w-full overflow-y-auto bg-bg-page">
      <main className="mx-auto w-full max-w-[960px] px-5 py-8 md:px-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-h2 text-text-1">{localize('com_skill_center_title')}</h1>
            <p className="mt-1 text-body-sm text-text-3">{localize('com_skill_center_subtitle')}</p>
          </div>
          <Button disabled={!identity.data || identity.isError} onClick={startUpload} className="max-[575px]:w-full">
            <Outlined.Plus />{localize('com_skill_center_upload')}
          </Button>
        </header>
        <div className="mt-5 flex items-start gap-3 rounded-lg bg-fill-1 px-3 py-2">
          <Tag color="warning">{localize('com_skill_center_preview')}</Tag>
          <p className="min-w-0 text-caption text-text-3">{localize('com_skill_center_preview_notice')}</p>
        </div>
        {saved && <p role="status" className="mt-4 text-body-sm text-text-2">{localize('com_skill_center_saved')}</p>}
        <div className="mb-3 mt-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <h2 className="text-h4 text-text-1">{localize('com_skill_center_my_skills')}</h2>
            <span className="text-caption tabular-nums text-text-3">{skills.length}</span>
          </div>
          <SearchInput value={search} onChange={(event) => setSearch(event.target.value)} onClear={() => setSearch('')} placeholder={localize('com_skill_center_search')} aria-label={localize('com_skill_center_search')} className="w-full min-[576px]:w-64" />
        </div>
        {failed && <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-base p-3 text-body-sm text-text-2">
          <p>{localize(identity.isError ? 'com_skill_center_error_identity' : platform.isError ? 'com_skill_center_error_platform' : 'com_skill_center_error_storage')}</p>
          <Button color="default" variant="outlined" size="small" loading={loading} onClick={retry}>{localize('com_skill_center_retry')}</Button>
        </div>}
        {loading && skills.length === 0 ? <div role="status" aria-label={localize('com_skill_center_loading')} className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: 8 }, (_, item) => <div key={item} className="h-32 rounded-xl border border-border-base p-4 motion-safe:animate-pulse"><div className="h-5 w-1/2 rounded bg-fill-2" /><div className="mt-4 h-3 w-full rounded bg-fill-1" /><div className="mt-2 h-3 w-3/4 rounded bg-fill-1" /></div>)}
        </div> : filtered.length ? <div className="grid gap-3 md:grid-cols-2">
          {filtered.map((skill) => <button
            key={skill.id}
            type="button"
            onClick={() => setSelectedId(skill.id)}
            className="group flex min-h-32 flex-col rounded-xl border border-border-base p-4 text-left transition-colors hover:border-blue-300 hover:bg-fill-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <div className="flex w-full items-start gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-fill-1 text-text-2"><Outlined.Newspaper className="size-4" /></span>
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-body font-medium text-text-1" title={skill.displayName}>{skill.displayName}</h3>
                <p className="mt-0.5 truncate text-caption text-text-3">{skill.name}</p>
              </div>
              <span className="pointer-events-none shrink-0 whitespace-nowrap text-caption text-text-2 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 coarse-pointer:opacity-100">{localize('com_skill_center_details')}<span aria-hidden className="ml-1">→</span></span>
            </div>
            <p className="mt-2 line-clamp-2 break-words text-body-sm text-text-3">{skill.description}</p>
          </button>)}
        </div> : <StateView
          title={localize(keyword ? 'com_skill_center_no_results' : failed ? 'com_skill_center_load_failed' : 'com_skill_center_empty')}
          description={localize(keyword ? 'com_skill_center_search_hint' : failed ? 'com_skill_center_retry_hint' : 'com_skill_center_empty_hint')}
          action={keyword ? <Button color="default" variant="outlined" onClick={() => setSearch('')}>{localize('com_skill_center_clear')}</Button> : !failed && <Button onClick={startUpload} disabled={!identity.data}>{localize('com_skill_center_upload')}</Button>}
        />}
      </main>
      {selected && !uploadOpen && <SkillDetails skill={selected} onClose={() => setSelectedId(undefined)} onUpdate={(skill) => { setTarget(skill); setUploadOpen(true); }} />}
      {uploadOpen && <SkillUploadDialog key={target?.id ?? 'new'} open onOpenChange={setUploadOpen} target={target} onSaved={() => { setSaved(true); setSelectedId(undefined); }} />}
    </div>
  );
}
