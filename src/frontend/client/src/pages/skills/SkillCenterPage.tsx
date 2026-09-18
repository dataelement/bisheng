import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { Button, SearchInput, StateView, Tabs } from '@bisheng/ui';
import { NotificationSeverity } from '~/common';
import {
  MODULE_HOME_COLUMN, MODULE_HOME_FRAME, ModuleHomeHeader, ModuleViewTabs, type ModuleView,
} from '~/components/ModuleHome';
import { SkillDetails } from '~/components/Skills/SkillDetails';
import { SkillUploadDialog } from '~/components/Skills/SkillUploadDialog';
import type { CenterSkill, PersonalSkill } from '~/components/Skills/types';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import { cn } from '~/utils';
import { SkillGrid, SkillGridSkeleton } from './SkillGrid';
import { SkillSquareBanner } from './SkillSquareBanner';

/**
 * 技能 module home, in the shared 我的 / 广场 frame (see ~/components/ModuleHome):
 *   我的  — skills the user uploaded; they can update, toggle and delete them.
 *   广场  — 技能广场: skills the enterprise provides to this account, read-only.
 * The view and the open detail live in the URL (`?view=square`, `?skill=<id>`) so the
 * chat input's skill menu can deep-link here.
 */
export function SkillCenterPage() {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const { identity, platform, personal } = useSkillCenter();
  const [search, setSearch] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [target, setTarget] = useState<PersonalSkill>();
  const [params, setParams] = useSearchParams();

  const skills = useMemo<CenterSkill[]>(() => [
    ...(platform.data ?? []), ...(personal.data ?? []),
  ].sort((left, right) => left.displayName.localeCompare(right.displayName)), [platform.data, personal.data]);
  const selected = skills.find((skill) => skill.id === params.get('skill'));
  // A deep link that only names a skill lands on the view that skill belongs to.
  const viewParam = params.get('view');
  const view: ModuleView = (viewParam ? viewParam === 'square' : selected?.source === 'platform') ? 'square' : 'mine';
  const source = view === 'square' ? 'platform' : 'personal';

  const keyword = search.trim().toLocaleLowerCase();
  const viewSkills = skills.filter((skill) => skill.source === source);
  const filtered = viewSkills.filter((skill) => `${skill.displayName} ${skill.name} ${skill.description}`.toLocaleLowerCase().includes(keyword));
  const viewQuery = view === 'square' ? platform : personal;
  const loading = identity.isLoading || viewQuery.isFetching;
  const failed = identity.isError || viewQuery.isError;

  const updateParams = (nextView: ModuleView, skillId?: string) => {
    const next = new URLSearchParams(params);
    if (nextView === 'square') next.set('view', 'square');
    else next.delete('view');
    if (skillId) next.set('skill', skillId);
    else next.delete('skill');
    setParams(next, { replace: true });
  };
  const handleViewChange = (nextView: ModuleView) => {
    updateParams(nextView);
    setSearch('');
  };
  const handleStartUpload = () => { setTarget(undefined); setUploadOpen(true); };
  const handleRetry = () => { void identity.refetch(); void viewQuery.refetch(); };
  const handleSaved = () => {
    handleViewChange('mine');
    showToast({ message: localize('com_skill_center_saved'), severity: NotificationSeverity.SUCCESS });
  };

  const searchInput = (
    <SearchInput
      value={search}
      onChange={(event) => setSearch(event.target.value)}
      onClear={() => setSearch('')}
      placeholder={localize('com_skill_center_search')}
      aria-label={localize('com_skill_center_search')}
      className="w-full min-[576px]:w-64"
    />
  );

  // Mobile has no floating switcher (see ModuleViewTabs); each view carries these tabs in flow.
  const mobileTabs = (
    <Tabs
      className="w-full shrink-0 md:hidden"
      activeKey={view}
      onChange={(key) => handleViewChange(key as ModuleView)}
      items={[
        { key: 'mine', label: localize('com_skill_center_my_skills'), badge: personal.data?.length },
        { key: 'square', label: localize('com_skill_center_square_title'), badge: platform.data?.length },
      ]}
    />
  );

  const emptyKind = keyword ? 'search' : failed ? 'failed' : view;
  const content = (
    <>
      {failed && (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-base p-3 text-body-sm text-text-2">
          <p>{localize(identity.isError ? 'com_skill_center_error_identity' : view === 'square' ? 'com_skill_center_error_platform' : 'com_skill_center_error_storage')}</p>
          <Button color="default" variant="outlined" size="small" loading={loading} onClick={handleRetry}>{localize('com_skill_center_retry')}</Button>
        </div>
      )}
      {loading && viewSkills.length === 0 ? <SkillGridSkeleton /> : filtered.length ? (
        <SkillGrid skills={filtered} onSelect={(skill) => updateParams(view, skill.id)} />
      ) : (
        <div className="flex flex-1 items-center justify-center py-10">
          <StateView
            title={localize({
              search: 'com_skill_center_no_results', failed: 'com_skill_center_load_failed',
              square: 'com_skill_center_square_empty', mine: 'com_skill_center_empty',
            }[emptyKind])}
            description={localize({
              search: 'com_skill_center_search_hint', failed: 'com_skill_center_retry_hint',
              square: 'com_skill_center_square_empty_hint', mine: 'com_skill_center_empty_hint',
            }[emptyKind])}
            action={emptyKind === 'search'
              ? <Button color="default" variant="outlined" onClick={() => setSearch('')}>{localize('com_skill_center_clear')}</Button>
              : emptyKind === 'mine' && <Button onClick={handleStartUpload} disabled={!identity.data}>{localize('com_skill_center_upload')}</Button>}
          />
        </div>
      )}
    </>
  );

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden bg-white">
      {/* Rendered once above both views so switching slides one indicator. */}
      <ModuleViewTabs className="max-md:hidden" active={view} onChange={handleViewChange} />
      {view === 'mine' ? (
        <div className={cn(MODULE_HOME_FRAME, 'max-md:px-4 max-md:pt-0')}>
          {mobileTabs}
          {/* Mobile shows the module title in the top bar instead. */}
          <div className="flex w-full justify-center max-md:hidden">
            <ModuleHomeHeader title={localize('com_skill_center_title')} />
          </div>
          <div className={cn(MODULE_HOME_COLUMN, 'mt-4 flex shrink-0 flex-wrap items-center gap-3')}>
            <p className="min-w-0 flex-1 truncate text-body-sm text-text-3 max-[575px]:basis-full">{localize('com_skill_center_subtitle')}</p>
            {searchInput}
            <Button disabled={!identity.data || identity.isError} onClick={handleStartUpload} className="max-[575px]:w-full">
              <Outlined.Plus />{localize('com_skill_center_upload')}
            </Button>
          </div>
          {/* The scroll area spans the full width so its scrollbar sits at the page edge. */}
          <div className="scroll-on-scroll flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
            <div className={cn(MODULE_HOME_COLUMN, 'flex flex-1 flex-col pb-3 pt-4')}>{content}</div>
          </div>
        </div>
      ) : (
        <div className="flex h-full min-h-0 w-full flex-col items-center overflow-hidden">
          <div className="w-full shrink-0 px-4 md:hidden">{mobileTabs}</div>
          <SkillSquareBanner />
          <div className="flex w-full max-w-[1000px] shrink-0 items-center justify-end px-5 py-5">{searchInput}</div>
          <main className="scrollbar-os flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
            <div className="flex w-full max-w-[1000px] flex-1 flex-col px-5 pb-5">{content}</div>
          </main>
        </div>
      )}
      {selected && !uploadOpen && (
        <SkillDetails
          skill={selected}
          onClose={() => updateParams(view)}
          onUpdate={(skill) => { setTarget(skill); setUploadOpen(true); }}
        />
      )}
      {uploadOpen && <SkillUploadDialog key={target?.id ?? 'new'} open onOpenChange={setUploadOpen} target={target} onSaved={handleSaved} />}
    </div>
  );
}
