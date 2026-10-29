import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthContext } from '~/hooks';
import { getCenterSkills, getSkillScope, setSkillAvailability, uploadPersonalSkill, deletePersonalSkill } from '~/api/skillCenter';
import { changePersonalSkill, listPersonalSkills } from './skillPreviewStore';
import { SkillError, type PersonalSkill, type PlatformSkill, type CenterSkill } from './types';

async function loadSkills(scope: string) {
  // Move existing browser-owned bundles once; the stable client ID makes retries idempotent.
  const legacy = await listPersonalSkills(scope);
  for (const row of legacy) {
    const id = await uploadPersonalSkill(row.file, row.fileName, undefined, row.id);
    if (!row.enabled) await setSkillAvailability({ ...row, resourceId: id }, false);
    await changePersonalSkill(scope, { kind: 'delete', target: row });
  }
  return getCenterSkills();
}

type Change = Parameters<typeof changePersonalSkill>[1] | { kind: 'toggle'; target: CenterSkill; enabled: boolean };
export function useSkillCenter() {
  const { user } = useAuthContext();
  const client = useQueryClient();
  const identity = useQuery(['skill-center', 'scope', user?.id], () => getSkillScope(String(user?.id)), { enabled: !!user?.id, retry: false, staleTime: 0 });
  const scope = identity.data;
  const catalog = useQuery(['skill-center', scope, 'catalog'], () => loadSkills(scope ?? ''), { enabled: !!scope, retry: false, refetchOnWindowFocus: true });
  const platform = { ...catalog, data: catalog.data?.filter((row): row is PlatformSkill => row.source === 'platform') };
  const personal = { ...catalog, data: catalog.data?.filter((row): row is PersonalSkill => row.source === 'personal') };
  const mutation = useMutation({
    mutationFn: async (change: Change) => {
      if (!scope || identity.isError) throw new SkillError('identity');
      if (change.kind === 'toggle') return setSkillAvailability(change.target, change.enabled);
      if (change.kind === 'delete') return deletePersonalSkill(change.target);
      return uploadPersonalSkill(change.file, change.manifest.fileName, change.target);
    },
    onSettled: async () => { await Promise.all([client.invalidateQueries(['skill-center', scope]), client.invalidateQueries(['capability-center']), client.invalidateQueries(['linsightSelectableSkills'])]); },
  });
  return { scope, identity, platform, personal, mutation };
}
