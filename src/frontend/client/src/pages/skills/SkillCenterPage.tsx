import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { Button, SearchInput, StateView, Tabs, Tooltip } from '@bisheng/ui';
import { NotificationSeverity } from '~/common';
import { ActionMenuCheckboxItem, ActionMenuContent } from '~/components/ActionMenu';
import { MODULE_HOME_COLUMN, MODULE_HOME_FRAME, ModuleHomeHeader } from '~/components/ModuleHome';
import { SkillDetails } from '~/components/Skills/SkillDetails';
import { SkillUploadDialog } from '~/components/Skills/SkillUploadDialog';
import type { CenterSkill, PersonalSkill } from '~/components/Skills/types';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { useLocalize } from '~/hooks';
import { isDemoId } from '~/mock/demo/ids';
import { useToastContext } from '~/Providers';
import { cn } from '~/utils';
import { SkillGrid, SkillGridSkeleton } from './SkillGrid';
import { SkillList, SkillListSkeleton, type SkillSort } from './SkillList';
import { SkillSquareBanner } from './SkillSquareBanner';

/**
 * 技能 module home, in the shared 我的 / 广场 frame (see ~/components/ModuleHome):
 *   我的  — every skill this account can use, as one list in two groups: what the user
 *           uploaded (a switch per row; update / delete in the details) and what the
 *           enterprise provides (always on).
 *   广场  — 技能广场: the enterprise skills as a card showcase, read-only.
 * The view and the open detail live in the URL (`?view=square`, `?skill=<id>`) so the
 * chat input's skill menu can deep-link here.
 */
type ModuleView = 'mine' | 'square';

export function SkillCenterPage() {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const { identity, platform, personal, mutation } = useSkillCenter();
  const [search, setSearch] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [target, setTarget] = useState<PersonalSkill>();
  // DEV sample rows are not in the store; their switch flips this session-only override.
  const [demoEnabled, setDemoEnabled] = useState<Record<string, boolean>>({});
  const [sort, setSort] = useState<SkillSort>('recent');
  const [params, setParams] = useSearchParams();

  const skills = useMemo<CenterSkill[]>(() => [
    ...(platform.data ?? []),
    ...(personal.data ?? []).map((skill) => (skill.id in demoEnabled ? { ...skill, enabled: demoEnabled[skill.id] } : skill)),
  ].sort((left, right) => left.displayName.localeCompare(right.displayName)), [platform.data, personal.data, demoEnabled]);
  const selected = skills.find((skill) => skill.id === params.get('skill'));
  // A deep link that only names a skill lands on the view that skill belongs to.
  const viewParam = params.get('view');
  const view: ModuleView = (viewParam ? viewParam === 'square' : selected?.source === 'platform') ? 'square' : 'mine';

  const keyword = search.trim().toLocaleLowerCase();
  const viewSkills = view === 'square' ? skills.filter((skill) => skill.source === 'platform') : skills;
  const filtered = viewSkills.filter((skill) => `${skill.displayName} ${skill.name} ${skill.description}`.toLocaleLowerCase().includes(keyword));
  // 我的 lists both sources; its error banner speaks for the personal store, and a failed
  // enterprise query there only leaves that group out.
  const viewQuery = view === 'square' ? platform : personal;
  const loading = identity.isLoading || viewQuery.isFetching || (view === 'mine' && platform.isLoading);
  const failed = identity.isError || viewQuery.isError;

  const updateParams = (nextView: ModuleView, skillId?: string) => {
    const next = new URLSearchParams(params);
    if (nextView === 'square') next.set('view', 'square');
    // A skill opened from 我的 pins the view: an enterprise skill would otherwise pull the
    // page over to the square, the view its bare deep link belongs to.
    else if (skillId) next.set('view', 'mine');
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
  const handleToggle = (skill: PersonalSkill, enabled: boolean) => {
    if (isDemoId(skill.id)) {
      setDemoEnabled((prev) => ({ ...prev, [skill.id]: enabled }));
      return;
    }
    mutation.mutate({ kind: 'toggle', target: skill, enabled }, {
      onError: () => showToast({ message: localize('com_skill_center_error_storage'), severity: NotificationSeverity.ERROR }),
    });
  };
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

  // 我的技能 / 技能广场 switch, in flow above either view.
  const viewTabs = (
    <Tabs
      className="w-full shrink-0"
      activeKey={view}
      onChange={(key) => handleViewChange(key as ModuleView)}
      items={[
        { key: 'mine', label: localize('com_skill_center_my_skills'), badge: personal.data?.length },
        { key: 'square', label: localize('com_skill_center_square_title'), badge: platform.data?.length },
      ]}
    />
  );

  // 我的 view's tools, in the module homes' shared order: search, sort, then create.
  const mineTools = (
    <>
      {searchInput}
      <DropdownMenu>
        <Tooltip content={localize('com_skill_center_sort')}>
          <DropdownMenuTrigger asChild>
            <Button color="default" variant="outlined" iconOnly aria-label={localize('com_skill_center_sort')}>
              <Outlined.Sort />
            </Button>
          </DropdownMenuTrigger>
        </Tooltip>
        <ActionMenuContent>
          <ActionMenuCheckboxItem checked={sort === 'recent'} onCheckedChange={() => setSort('recent')}>
            {localize('com_skill_center_sort_recent')}
          </ActionMenuCheckboxItem>
          <ActionMenuCheckboxItem checked={sort === 'name'} onCheckedChange={() => setSort('name')}>
            {localize('com_skill_center_sort_name')}
          </ActionMenuCheckboxItem>
        </ActionMenuContent>
      </DropdownMenu>
      <Button disabled={!identity.data || identity.isError} onClick={handleStartUpload} className="max-[575px]:w-full">
        <Outlined.Plus />{localize('com_skill_center_upload')}
      </Button>
    </>
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
      {loading && viewSkills.length === 0 ? (view === 'mine' ? <SkillListSkeleton /> : <SkillGridSkeleton />) : filtered.length ? (
        view === 'mine' ? (
          <SkillList
            skills={filtered}
            sort={sort}
            pendingId={mutation.isLoading ? mutation.variables?.target?.id : undefined}
            onSelect={(skill) => updateParams('mine', skill.id)}
            onToggle={handleToggle}
            createdEmptyHint={keyword ? undefined : (
              <p className="px-2 py-3 text-body-sm text-text-3">{localize('com_skill_center_empty_hint')}</p>
            )}
          />
        ) : (
          <SkillGrid skills={filtered} onSelect={(skill) => updateParams(view, skill.id)} />
        )
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
      {view === 'mine' ? (
        <div className={cn(MODULE_HOME_FRAME, 'max-md:px-4 max-md:pt-0')}>
          {viewTabs}
          {/* Desktop: the shared header row — title left, tools right (create last). */}
          <div className="mt-4 flex w-full justify-center max-md:hidden">
            <ModuleHomeHeader title={localize('com_skill_center_title')}>{mineTools}</ModuleHomeHeader>
          </div>
          <div className={cn(MODULE_HOME_COLUMN, 'mt-4 flex shrink-0 flex-wrap items-center gap-3')}>
            <p className="min-w-0 flex-1 truncate text-body-sm text-text-3 max-[575px]:basis-full">{localize('com_skill_center_subtitle')}</p>
            {/* Mobile has no header row (the top bar carries the title), so the tools stay in flow. */}
            <div className="contents md:hidden">{mineTools}</div>
          </div>
          {/* The scroll area spans the full width so its scrollbar sits at the page edge. */}
          <div className="scroll-on-scroll flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
            <div className={cn(MODULE_HOME_COLUMN, 'flex flex-1 flex-col pb-3 pt-4')}>{content}</div>
          </div>
        </div>
      ) : (
        <div className="flex h-full min-h-0 w-full flex-col items-center overflow-hidden">
          <div className="w-full shrink-0 px-4 md:px-3 md:pt-5">{viewTabs}</div>
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
          toggling={mutation.isLoading && mutation.variables?.kind === 'toggle'}
          onClose={() => updateParams(view)}
          onToggle={handleToggle}
          onUpdate={(skill) => { setTarget(skill); setUploadOpen(true); }}
        />
      )}
      {uploadOpen && <SkillUploadDialog key={target?.id ?? 'new'} open onOpenChange={setUploadOpen} target={target} onSaved={handleSaved} />}
    </div>
  );
}
