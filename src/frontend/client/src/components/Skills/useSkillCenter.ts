import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { deletePersonalSkill, getSkillCenter, setPersonalSkillEnabled, setSkillAvailability, getSkillScope } from '~/api/skillCenter';
import { useAuthContext } from "~/hooks";
import type { SkillRecord } from './types';

type SkillChange = { kind: 'toggle'; target: SkillRecord; enabled: boolean } | { kind: 'delete'; target: SkillRecord };


export function useSkillCenter() {
  const client = useQueryClient();
  const { user } = useAuthContext();
  const identity = useQuery(["skill-center", "scope", user?.id], () => getSkillScope(String(user?.id)), {
    enabled: !!user?.id, retry: false, staleTime: 0,
  });
  const centerKey = ["skill-center", identity.data];
  const center = useQuery(centerKey, () => getSkillCenter(), { retry: false, enabled: !!identity.data });
  const refresh = async () => {
    await client.invalidateQueries(centerKey);
    await client.invalidateQueries(["linsightSelectableSkills"]);
    await client.invalidateQueries(["capability-center"]);
  };
  const mutation = useMutation<SkillRecord | void, unknown, SkillChange>({
    mutationFn: (change: SkillChange) => {
      if (change.kind === 'delete') return deletePersonalSkill(change.target.id);
      if (change.target.source === "platform") return setSkillAvailability(change.target, change.enabled);
      return setPersonalSkillEnabled(change.target.id, change.enabled);
    },
    onSettled: refresh,
  });
  const queryOf = (rows: SkillRecord[] | undefined) => ({
    data: rows,
    isLoading: identity.isLoading || (!identity.isError && center.isLoading),
    isFetching: center.isFetching,
    isError: identity.isError || center.isError,
    isSuccess: center.isSuccess,
    refetch: center.refetch,
  });
  return {
    center,
    identity,
    personal: queryOf(center.data?.personal),
    platform: queryOf(center.data?.enterprise),
    personalCount: center.data?.personalCount ?? 0,
    enterpriseCount: center.data?.enterpriseCount ?? 0,
    mutation,
    refresh,
  };
}
