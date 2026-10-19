import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthContext } from '~/hooks';
import { getAvailableCenterSkills, getSkillScope } from '~/api/skillCenter';
import { changePersonalSkill, listPersonalSkills } from './skillPreviewStore';
import { SkillError, type PersonalSkill } from './types';

async function loadPersonalSkills(scope: string): Promise<PersonalSkill[]> {
  const rows = await listPersonalSkills(scope);
  // DEV only, opt-in sample rows (~/mock/demo). The DEV guard is a build-time constant, so
  // the branch — and the dynamic import's chunk with it — is dropped from production bundles.
  if (!import.meta.env.DEV) return rows;
  const { demoPersonalSkills } = await import('~/mock/demo/skills');
  return [...rows, ...demoPersonalSkills(scope)];
}

export function useSkillCenter() {
  const { user } = useAuthContext();
  const client = useQueryClient();
  const identity = useQuery(['skill-center', 'scope', user?.id], () => getSkillScope(String(user?.id)), {
    enabled: !!user?.id, retry: false, staleTime: 0,
  });
  const scope = identity.data;
  const platform = useQuery(['skill-center', scope, 'platform'], getAvailableCenterSkills, { enabled: !!scope, retry: false });
  const personal = useQuery(['skill-center', scope, 'personal'], () => loadPersonalSkills(scope ?? ''), { enabled: !!scope, retry: false });
  const mutation = useMutation({
    mutationFn: (change: Parameters<typeof changePersonalSkill>[1]) => {
      if (!scope || identity.isError) throw new SkillError('identity');
      return changePersonalSkill(scope, change);
    },
    onSettled: () => client.invalidateQueries(['skill-center', scope, 'personal']),
  });
  return { scope, identity, platform, personal, mutation };
}
