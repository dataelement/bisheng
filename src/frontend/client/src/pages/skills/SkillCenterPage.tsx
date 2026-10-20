import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import { Button, SearchInput, StateView, Tooltip } from '@bisheng/ui';
import { translateApiErrorMessage } from '~/api/request';
import { NotificationSeverity } from '~/common';
import { ActionMenuCheckboxItem, ActionMenuContent } from '~/components/ActionMenu';
import { MODULE_HOME_COLUMN, MODULE_HOME_FRAME, ModuleHomeHeader } from '~/components/ModuleHome';
import { SkillDetails } from '~/components/Skills/SkillDetails';
import { SkillUploadDialog } from '~/components/Skills/SkillUploadDialog';
import { SkillRequestError, type SkillRecord } from '~/components/Skills/types';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import { cn } from '~/utils';
import { SkillList, SkillListSkeleton, type SkillSort } from './SkillList';

/**
 * Skill center: one list in two groups. Skills the user uploaded have a switch
 * per row, with update and delete in the details. Skills the enterprise provides
 * stay on. The open detail lives in the URL (`?skill=<id>`).
 */

export function SkillCenterPage() {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const { platform, personal, mutation, personalCount, enterpriseCount } = useSkillCenter();
  const [search, setSearch] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [target, setTarget] = useState<SkillRecord>();
  const [enabledOverride, setEnabledOverride] = useState<Record<number, boolean>>({});
  const [notice, setNotice] = useState('');
  const [sort, setSort] = useState<SkillSort>('recent');
  const [params, setParams] = useSearchParams();

  const skills = useMemo<SkillRecord[]>(() => [
    ...(platform.data ?? []),
    ...(personal.data ?? []),
  ].map((skill) => (skill.id in enabledOverride ? { ...skill, enabled: enabledOverride[skill.id] } : skill))
    .sort((left, right) => left.displayName.localeCompare(right.displayName)), [platform.data, personal.data, enabledOverride]);
  const requestedId = Number(params.get('skill'));
  const selected = Number.isInteger(requestedId) ? skills.find((skill) => skill.id === requestedId) : undefined;
  const keyword = search.trim().toLocaleLowerCase();
  const filtered = skills.filter((skill) => `${skill.displayName} ${skill.name} ${skill.description}`.toLocaleLowerCase().includes(keyword));
  const loading = personal.isLoading || personal.isFetching;
  const failed = personal.isError;

  const updateParams = (skillId?: string) => {
    const next = new URLSearchParams(params);
    next.delete('view');
    if (skillId) next.set('skill', skillId);
    else next.delete('skill');
    setParams(next, { replace: true });
  };
  const handleStartUpload = () => { setTarget(undefined); setUploadOpen(true); };
  const handleRetry = () => { void personal.refetch(); };
  const handleToggle = (skill: SkillRecord, enabled: boolean) => {
    setEnabledOverride((prev) => ({ ...prev, [skill.id]: enabled }));
    mutation.mutate({ kind: 'toggle', target: skill, enabled }, {
      onError: (error) => {
        setEnabledOverride((prev) => ({ ...prev, [skill.id]: skill.enabled }));
        // skip403Redirect already toasts the translated business error and rejects
        // with status_code set. A maintenance overlay covers HTTP 500.
        const explained = typeof error === 'object' && error !== null && 'status_code' in error
          && !(error instanceof SkillRequestError);
        const httpStatus = typeof error === 'object' && error !== null && 'response' in error
          ? (error as { response?: { status?: number } }).response?.status
          : undefined;
        if (explained || httpStatus === 500) return;
        const message = error instanceof SkillRequestError
          ? translateApiErrorMessage({
            status_code: error.statusCode,
            status_message: error.statusMessage,
            data: error.data,
          })
          : '';
        showToast({
          message: message || localize('com_skill_center_error_storage'),
          severity: NotificationSeverity.ERROR,
        });
      },
    });
  };
  const handleSaved = () => {
    setSearch('');
    updateParams();
    showToast({ message: localize('com_skill_center_saved'), severity: NotificationSeverity.SUCCESS });
  };
  useEffect(() => {
    if (!params.get('skill') || personal.isLoading || personal.isFetching) return;
    if (selected) {
      setNotice('');
      return;
    }
    setNotice(localize('com_skill_center_unavailable'));
    updateParams();
    // updateParams is stable enough for this URL cleanup; including it retriggers the clear.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, selected, personal.isLoading, personal.isFetching]);

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

  // Tools, in the module homes' shared order: search, sort, then create.
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
      <Button disabled={personal.isError || personal.isLoading} onClick={handleStartUpload} className="max-[575px]:w-full">
        <Outlined.Plus />{localize('com_skill_center_upload')}
      </Button>
    </>
  );

  const emptyKind = keyword ? 'search' : failed ? 'failed' : 'mine';
  const content = (
    <>
      {notice && <p role="alert" className="mb-4 text-body-sm text-text-2">{notice}</p>}
      {failed && (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-base p-3 text-body-sm text-text-2">
          <p>{localize('com_skill_center_load_failed')}</p>
          <Button color="default" variant="outlined" size="small" loading={loading} onClick={handleRetry}>{localize('com_skill_center_retry')}</Button>
        </div>
      )}
      {loading && skills.length === 0 ? <SkillListSkeleton /> : filtered.length ? (
        <SkillList
          skills={filtered}
          sort={sort}
          createdCount={personalCount}
          providedCount={enterpriseCount}
          pendingId={mutation.isLoading ? mutation.variables?.target?.id : undefined}
          onSelect={(skill) => updateParams(String(skill.id))}
          onToggle={handleToggle}
          createdEmptyHint={keyword ? undefined : (
            <p className="px-2 py-3 text-body-sm text-text-3">{localize('com_skill_center_empty_hint')}</p>
          )}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center py-10">
          <StateView
            title={localize({
              search: 'com_skill_center_no_results', failed: 'com_skill_center_load_failed', mine: 'com_skill_center_empty',
            }[emptyKind])}
            description={localize({
              search: 'com_skill_center_search_hint', failed: 'com_skill_center_retry_hint', mine: 'com_skill_center_empty_hint',
            }[emptyKind])}
            action={emptyKind === 'search'
              ? <Button color="default" variant="outlined" onClick={() => setSearch('')}>{localize('com_skill_center_clear')}</Button>
              : <Button onClick={handleStartUpload} disabled={personal.isError}>{localize('com_skill_center_upload')}</Button>}
          />
        </div>
      )}
    </>
  );

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden bg-white">
      <div className={cn(MODULE_HOME_FRAME, 'max-md:px-4 max-md:pt-0')}>
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
      {selected && !uploadOpen && (
        <SkillDetails
          skill={selected}
          toggling={mutation.isLoading && mutation.variables?.kind === 'toggle'}
          onClose={() => updateParams()}
          onToggle={handleToggle}
          onUpdate={(skill) => { setTarget(skill); setUploadOpen(true); }}
        />
      )}
      {uploadOpen && <SkillUploadDialog key={target?.id ?? 'new'} open onOpenChange={setUploadOpen} target={target} onSaved={handleSaved} />}
    </div>
  );
}
