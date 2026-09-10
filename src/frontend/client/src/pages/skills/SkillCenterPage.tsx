import { useMemo, useState } from 'react';
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
  const [selectedId, setSelectedId] = useState<string>();
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
      <main className="mx-auto w-full max-w-[1040px] px-5 pb-12 pt-10 md:px-10 md:pt-16">
        <header className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <h1 className="text-h2 text-text-1">{localize('com_skill_center_title')}</h1>
            <p className="mt-2 text-body text-text-3">{localize('com_skill_center_subtitle')}</p>
          </div>
          <Button size="large" disabled={!identity.data || identity.isError} onClick={startUpload} className="max-[575px]:w-full">
            <Outlined.Plus />{localize('com_skill_center_upload')}
          </Button>
        </header>
        <div className="mt-7 flex items-start gap-3 rounded-xl bg-fill-1 px-4 py-3">
          <Tag color="warning">{localize('com_skill_center_preview')}</Tag>
          <p className="min-w-0 text-caption text-text-3">{localize('com_skill_center_preview_notice')}</p>
        </div>
        {saved && <p role="status" className="mt-4 text-body-sm text-text-2">{localize('com_skill_center_saved')}</p>}
        <div className="mb-5 mt-8 flex flex-wrap items-center justify-between gap-4">
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
        {loading && skills.length === 0 ? <div role="status" aria-label={localize('com_skill_center_loading')} className="grid gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((item) => <div key={item} className="h-44 rounded-xl border border-border-base p-5 motion-safe:animate-pulse"><div className="h-5 w-1/2 rounded bg-fill-2" /><div className="mt-5 h-3 w-full rounded bg-fill-1" /><div className="mt-3 h-3 w-3/4 rounded bg-fill-1" /></div>)}
        </div> : filtered.length ? <div className="grid gap-4 md:grid-cols-2">
          {filtered.map((skill) => <button
            key={skill.id}
            type="button"
            onClick={() => setSelectedId(skill.id)}
            className="group flex min-h-44 flex-col rounded-xl border border-border-base p-5 text-left transition-colors hover:border-blue-300 hover:bg-fill-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <div className="flex w-full items-start gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-fill-1 text-text-2"><Outlined.Newspaper className="size-5" /></span>
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-h4 text-text-1" title={skill.displayName}>{skill.displayName}</h3>
                <p className="mt-1 truncate text-caption text-text-3">{skill.name}</p>
              </div>
            </div>
            <p className="mb-5 mt-4 line-clamp-2 break-words text-body-sm text-text-3">{skill.description}</p>
            <div className="mt-auto flex w-full items-center justify-between gap-3">
              <span className="text-caption text-text-3">{localize(skill.source === 'personal' ? skill.enabled ? 'com_skill_center_preview_enabled' : 'com_skill_center_disabled' : 'com_skill_center_available')}</span>
              <span className="text-caption text-text-2">{localize('com_skill_center_details')}<span aria-hidden className="ml-1">→</span></span>
            </div>
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
