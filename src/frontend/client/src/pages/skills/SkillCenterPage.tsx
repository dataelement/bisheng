import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { Button, SearchInput, StateView, Tooltip } from '@bisheng/ui';
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
import { SkillList, SkillListSkeleton, type SkillSort } from './SkillList';

/**
 * 技能中心 — every skill this account can use, as one list in two groups: what the user
 * uploaded (a switch per row; update / delete in the details) and what the enterprise
 * provides (always on). The open detail lives in the URL (`?skill=<id>`) so the chat
 * input's skill menu can deep-link here.
 */
type EmptyKind = 'search' | 'failed' | 'empty';

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

  const keyword = search.trim().toLocaleLowerCase();
  const filtered = skills.filter((skill) => `${skill.displayName} ${skill.name} ${skill.description}`.toLocaleLowerCase().includes(keyword));
  // Both the personal store and the enterprise list are shown here, so a failure in
  // either is reported above the list — this page is the only place listing them.
  const loading = identity.isLoading || personal.isFetching || platform.isLoading;
  const failed = identity.isError || personal.isError || platform.isError;

  /** The open detail is the page's only URL state; `view` is a leftover of the retired 广场. */
  const openSkill = (skillId?: string) => {
    const next = new URLSearchParams(params);
    next.delete('view');
    if (skillId) next.set('skill', skillId);
    else next.delete('skill');
    setParams(next, { replace: true });
  };
  const handleStartUpload = () => { setTarget(undefined); setUploadOpen(true); };
  const handleRetry = () => {
    void identity.refetch();
    void personal.refetch();
    void platform.refetch();
  };
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
    // Clear the filter, otherwise the skill just saved can land outside it.
    setSearch('');
    showToast({ message: localize('com_skill_center_saved'), severity: NotificationSeverity.SUCCESS });
  };

  // The page's tools, in the module homes' shared order: search, sort, then create.
  const tools = (
    <>
      <SearchInput
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        onClear={() => setSearch('')}
        placeholder={localize('com_skill_center_search')}
        aria-label={localize('com_skill_center_search')}
        className="w-full min-[576px]:w-64"
      />
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

  const emptyKind: EmptyKind = keyword ? 'search' : failed ? 'failed' : 'empty';
  const content = (
    <>
      {failed && (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-base p-3 text-body-sm text-text-2">
          <p>{localize(identity.isError
            ? 'com_skill_center_error_identity'
            : personal.isError ? 'com_skill_center_error_storage' : 'com_skill_center_error_platform')}</p>
          <Button color="default" variant="outlined" size="small" loading={loading} onClick={handleRetry}>{localize('com_skill_center_retry')}</Button>
        </div>
      )}
      {loading && skills.length === 0 ? <SkillListSkeleton /> : filtered.length ? (
        <SkillList
          skills={filtered}
          sort={sort}
          pendingId={mutation.isLoading ? mutation.variables?.target?.id : undefined}
          onSelect={(skill) => openSkill(skill.id)}
          onToggle={handleToggle}
          createdEmptyHint={keyword ? undefined : (
            <p className="px-2 py-3 text-body-sm text-text-3">{localize('com_skill_center_empty_hint')}</p>
          )}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center py-10">
          <StateView
            title={localize({
              search: 'com_skill_center_no_results', failed: 'com_skill_center_load_failed',
              empty: 'com_skill_center_empty',
            }[emptyKind])}
            description={localize({
              search: 'com_skill_center_search_hint', failed: 'com_skill_center_retry_hint',
              empty: 'com_skill_center_empty_hint',
            }[emptyKind])}
            action={emptyKind === 'search'
              ? <Button color="default" variant="outlined" onClick={() => setSearch('')}>{localize('com_skill_center_clear')}</Button>
              : emptyKind === 'empty' && <Button onClick={handleStartUpload} disabled={!identity.data}>{localize('com_skill_center_upload')}</Button>}
          />
        </div>
      )}
    </>
  );

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden bg-white">
      <div className={cn(MODULE_HOME_FRAME, 'max-md:px-4')}>
        {/* Desktop: the shared header row — title left, tools right (create last). */}
        <div className="flex w-full justify-center max-md:hidden">
          <ModuleHomeHeader title={localize('com_skill_center_title')}>{tools}</ModuleHomeHeader>
        </div>
        <div className={cn(MODULE_HOME_COLUMN, 'mt-4 flex shrink-0 flex-wrap items-center gap-3 max-md:mt-0')}>
          <p className="min-w-0 flex-1 truncate text-body-sm text-text-3 max-[575px]:basis-full">{localize('com_skill_center_subtitle')}</p>
          {/* Mobile has no header row (the top bar carries the title), so the tools stay in flow. */}
          <div className="contents md:hidden">{tools}</div>
        </div>
        {/* The scroll area spans the full width so its scrollbar sits at the page edge. */}
        <div className="scroll-on-scroll flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
          <div className={cn(MODULE_HOME_COLUMN, 'flex flex-1 flex-col pb-3 pt-4')}>{content}</div>
        </div>
      </div>
      {selected && !uploadOpen && (
        <SkillDetails
          skill={selected}
          toggling={mutation.isLoading && mutation.variables?.kind === 'toggle'}
          onClose={() => openSkill()}
          onToggle={handleToggle}
          onUpdate={(skill) => { setTarget(skill); setUploadOpen(true); }}
        />
      )}
      {uploadOpen && <SkillUploadDialog key={target?.id ?? 'new'} open onOpenChange={setUploadOpen} target={target} onSaved={handleSaved} />}
    </div>
  );
}
