import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthContext } from '~/hooks';
import { getAvailableCenterSkills, getSkillScope } from '~/api/skillCenter';
import { changePersonalSkill, listPersonalSkills } from './skillPreviewStore';
import { SkillError } from './types';

export function useSkillCenter() {
  const { user } = useAuthContext();
  const client = useQueryClient();
  const identity = useQuery(['skill-center', 'scope', user?.id], () => getSkillScope(String(user?.id)), {
    enabled: !!user?.id, retry: false, staleTime: 0,
  });
  const scope = identity.data;
  const platform = useQuery(['skill-center', scope, 'platform'], getAvailableCenterSkills, { enabled: !!scope, retry: false });
  const personal = useQuery(['skill-center', scope, 'personal'], () => listPersonalSkills(scope ?? ''), { enabled: !!scope, retry: false });
  const mutation = useMutation({
    mutationFn: (change: Parameters<typeof changePersonalSkill>[1]) => {
      if (!scope || identity.isError) throw new SkillError('identity');
      return changePersonalSkill(scope, change);
    },
    onSettled: () => client.invalidateQueries(['skill-center', scope, 'personal']),
  });
  return { scope, identity, platform, personal, mutation };
}
