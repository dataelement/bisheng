import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, SearchInput, StateView } from '@bisheng/ui';
import { SkillDetails } from '~/components/Skills/SkillDetails';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { useLocalize } from '~/hooks';
import { SkillGrid, SkillGridSkeleton } from './SkillGrid';
import { SkillSquareBanner } from './SkillSquareBanner';

const noop = () => undefined;

/**
 * 技能广场 as a self-contained pane for the unified 广场: the enterprise skills as a card
 * showcase, read-only. The open detail lives in the URL (`?skill=<id>`) so the chat
 * input's skill menu can deep-link to it.
 */
export function SkillSquarePane() {
  const localize = useLocalize();
  const { identity, platform } = useSkillCenter();
  const [search, setSearch] = useState('');
  const [params, setParams] = useSearchParams();

  const skills = [...(platform.data ?? [])].sort((left, right) => left.displayName.localeCompare(right.displayName));
  const keyword = search.trim().toLocaleLowerCase();
  const filtered = skills.filter((skill) => `${skill.displayName} ${skill.name} ${skill.description}`.toLocaleLowerCase().includes(keyword));
  const selected = skills.find((skill) => skill.id === params.get('skill'));
  const loading = identity.isLoading || platform.isFetching;
  const failed = identity.isError || platform.isError;

  const handleSelect = (skillId?: string) => {
    const next = new URLSearchParams(params);
    if (skillId) next.set('skill', skillId);
    else next.delete('skill');
    setParams(next, { replace: true });
  };
  const handleRetry = () => { void identity.refetch(); void platform.refetch(); };

  const emptyKind = keyword ? 'search' : failed ? 'failed' : 'square';
  return (
    <div className="flex h-full min-h-0 w-full flex-col items-center overflow-hidden">
      <SkillSquareBanner />
      <div className="flex w-full max-w-[1000px] shrink-0 items-center justify-end px-5 py-5">
        <SearchInput
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          onClear={() => setSearch('')}
          placeholder={localize('com_skill_center_search')}
          aria-label={localize('com_skill_center_search')}
          className="w-full min-[576px]:w-64"
        />
      </div>
      <main className="scrollbar-os flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto">
        <div className="flex w-full max-w-[1000px] flex-1 flex-col px-5 pb-5">
          {failed && (
            <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border-base p-3 text-body-sm text-text-2">
              <p>{localize(identity.isError ? 'com_skill_center_error_identity' : 'com_skill_center_error_platform')}</p>
              <Button color="default" variant="outlined" size="small" loading={loading} onClick={handleRetry}>{localize('com_skill_center_retry')}</Button>
            </div>
          )}
          {loading && skills.length === 0 ? <SkillGridSkeleton /> : filtered.length ? (
            <SkillGrid skills={filtered} onSelect={(skill) => handleSelect(skill.id)} />
          ) : (
            <div className="flex flex-1 items-center justify-center py-10">
              <StateView
                title={localize({
                  search: 'com_skill_center_no_results', failed: 'com_skill_center_load_failed', square: 'com_skill_center_square_empty',
                }[emptyKind])}
                description={localize({
                  search: 'com_skill_center_search_hint', failed: 'com_skill_center_retry_hint', square: 'com_skill_center_square_empty_hint',
                }[emptyKind])}
                action={emptyKind === 'search' && (
                  <Button color="default" variant="outlined" onClick={() => setSearch('')}>{localize('com_skill_center_clear')}</Button>
                )}
              />
            </div>
          )}
        </div>
      </main>
      {/* Enterprise skills are read-only: the detail has nothing to toggle or update. */}
      {selected && <SkillDetails skill={selected} onClose={() => handleSelect()} onToggle={noop} onUpdate={noop} />}
    </div>
  );
}
