import { isApiError } from '@bisheng/api-client';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Button, StateView } from '@bisheng/ui';
import { translateApiErrorMessage } from '~/api/request';
import { NotificationSeverity } from '~/common';

import { SkillDetails } from '~/components/Skills/SkillDetails';
import { SkillUploadDialog } from '~/components/Skills/SkillUploadDialog';
import { type SkillRecord } from '~/components/Skills/types';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { useLocalize } from '~/hooks';

import { useToastContext } from '~/Providers';

import { SkillList, SkillListSkeleton, type SkillSort } from './SkillList';

/**
 * Skill center: one list in two groups. Skills the user uploaded have a switch
 * per row, with update and delete in the details. Skills the enterprise provides
 * stay on. The open detail lives in the URL (`?skill=<id>`).
 */

interface SkillCenterPaneProps { search: string; uploadOpen: boolean; onUploadOpenChange: (open: boolean) => void; onSearchClear?: () => void }
export function SkillCenterPane({ search, uploadOpen, onUploadOpenChange: setUploadOpen, onSearchClear }: SkillCenterPaneProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const { platform, personal, mutation, personalCount, enterpriseCount } = useSkillCenter();
  const [target, setTarget] = useState<SkillRecord>();
  const [enabledOverride, setEnabledOverride] = useState<Record<number, boolean>>({});
  const [notice, setNotice] = useState('');
  const sort: SkillSort = 'recent';
  const [params, setParams] = useSearchParams();

  const skills = useMemo<SkillRecord[]>(() => [
    ...(platform.data ?? []),
    ...(personal.data ?? []),
  ].map((skill) => (skill.id in enabledOverride ? { ...skill, enabled: enabledOverride[skill.id] } : skill)), [platform.data, personal.data, enabledOverride]);
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
        if (isApiError(error) && (error.presentation !== 'none' || error.kind === 'canceled')) return;
        const message = isApiError(error)
          ? translateApiErrorMessage({
            status_code: error.status_code,
            status_message: error.status_message,
            data: error.data,
          })
          : '';
        showToast({
          message: message || localize('com_skill_center_error_storage'),
          severity: NotificationSeverity.ERROR,
        });
        if (isApiError(error)) error.presentation = 'toast';
      },
    });
  };
  const handleSaved = () => {
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
              ? <Button color="default" variant="outlined" onClick={onSearchClear}>{localize('com_skill_center_clear')}</Button>
              : <Button onClick={handleStartUpload} disabled={personal.isError}>{localize('com_skill_center_upload')}</Button>}
          />
        </div>
      )}
    </>
  );

  return (
    <>
      {content}
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
    </>
  );
}
