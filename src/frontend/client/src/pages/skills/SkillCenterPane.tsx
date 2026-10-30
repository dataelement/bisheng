import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, StateView } from '@bisheng/ui';
import { SkillDetails } from '~/components/Skills/SkillDetails';
import { SkillUploadDialog } from '~/components/Skills/SkillUploadDialog';
import { useSkillCenter } from '~/components/Skills/useSkillCenter';
import { matchesSkillSearch } from '~/components/Skills/localization';
import type { PersonalSkill } from '~/components/Skills/types';
import { useLocalize } from '~/hooks';
import { SkillList, SkillListSkeleton } from './SkillList';
interface Props { search: string; uploadOpen: boolean; onUploadOpenChange: (open: boolean) => void }
export function SkillCenterPane({ search, uploadOpen, onUploadOpenChange }: Props) {
  const { identity, platform, personal, mutation } = useSkillCenter();
  const localize = useLocalize();
  const [params, setParams] = useSearchParams();
  const [target, setTarget] = useState<PersonalSkill>();
  const skills = [...platform.data ?? [], ...personal.data ?? []];
  const keyword = search.trim().toLocaleLowerCase();
  const filtered = skills.filter(skill => matchesSkillSearch(skill, keyword));
  const selected = skills.find(skill => skill.id === params.get('skill'));
  const select = (id?: string) => { const next = new URLSearchParams(params); if (id) next.set('skill', id); else next.delete('skill'); setParams(next, { replace: true }); };
  const pendingId = mutation.isLoading ? mutation.variables?.target?.id : undefined;
  return <>
    {identity.isError || platform.isError ? <StateView title={localize('com_skill_center_load_failed')} action={<Button onClick={() => { void identity.refetch(); void platform.refetch(); }}>{localize('com_skill_center_retry')}</Button>} />
    : identity.isLoading || platform.isLoading ? <SkillListSkeleton />
    : <SkillList skills={filtered} sort="recent" pendingId={pendingId} onSelect={skill => select(skill.id)}
        onToggle={(skill, enabled) => mutation.mutate({ kind: 'toggle', target: skill, enabled })}
        createdEmptyHint={keyword ? undefined : <p className="px-2 py-3 text-body-sm text-text-3">{localize('com_skill_center_empty_hint')}</p>} />}
    {mutation.isError && <p role="alert" className="text-body-sm text-danger">{localize('com_skill_center_error_storage')}</p>}
    {selected && !uploadOpen && <SkillDetails skill={selected} toggling={pendingId === selected.id} onClose={() => select()}
      onToggle={(skill, enabled) => mutation.mutate({ kind: 'toggle', target: skill, enabled })}
      onUpdate={skill => { setTarget(skill); onUploadOpenChange(true); }} />}
    {uploadOpen && <SkillUploadDialog open target={target} onOpenChange={open => { onUploadOpenChange(open); if (!open) setTarget(undefined); }} onSaved={() => select()} />}
  </>;
}
