import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { deletePersonalSkill, getSkillCenter, setPersonalSkillEnabled } from '~/api/skillCenter';
import type { SkillRecord } from './types';

const centerKey = ['skill-center'];

export function useSkillCenter() {
  const client = useQueryClient();
  const center = useQuery(centerKey, () => getSkillCenter(), { retry: false });
  const refresh = () => client.invalidateQueries(centerKey);
  const mutation = useMutation({
    mutationFn: (change: { kind: 'toggle'; target: SkillRecord; enabled: boolean } | { kind: 'delete'; target: SkillRecord }) => {
      if (change.kind === 'delete') return deletePersonalSkill(change.target.id);
      return setPersonalSkillEnabled(change.target.id, change.enabled);
    },
    onSettled: refresh,
  });
  const queryOf = (rows: SkillRecord[] | undefined) => ({
    data: rows,
    isLoading: center.isLoading,
    isFetching: center.isFetching,
    isError: center.isError,
    isSuccess: center.isSuccess,
    refetch: center.refetch,
  });
  return {
    center,
    personal: queryOf(center.data?.personal),
    platform: queryOf(center.data?.enterprise),
    personalCount: center.data?.personalCount ?? 0,
    enterpriseCount: center.data?.enterpriseCount ?? 0,
    mutation,
    refresh,
  };
}
