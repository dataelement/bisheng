import { useQuery } from '@tanstack/react-query';
import { checkResourceAction } from '~/api/permission';
import type { SelectedOrgKb } from '~/store/modeltype';
import { useAuthContext } from './AuthContext';
import useLocalize from './useLocalize';

/** Persisted scope is intent; only the permission service establishes current access. */
export function useKnowledgeSpaceAccess<T extends SelectedOrgKb>(selection: T[], scope: string, enabled = true) {
  const { user } = useAuthContext();
  const localize = useLocalize();
  const ids = [...new Set(selection.filter((item) => item.type === 'space').map((item) => item.id))].sort();
  const active = enabled && ids.length > 0;
  const query = useQuery({
    queryKey: ['chatKnowledgeAccess', user?.id, scope, ids],
    queryFn: async ({ signal }) => Object.fromEntries(await Promise.all(ids.map(async (id) => {
      const result = await checkResourceAction({
        resource_type: 'knowledge_space', resource_id: id, action: 'visible',
      }, { signal });
      if (typeof result?.allowed !== 'boolean') throw new Error('Invalid space permission result');
      return [id, result.allowed] as const;
    }))),
    enabled: active && user?.id != null,
    staleTime: 0,
    cacheTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
  });
  const unavailable = active
    ? selection.filter((item) => item.type === 'space' && query.data?.[item.id] === false) : [];
  const available = unavailable.length
    ? selection.filter((item) => item.type !== 'space' || query.data?.[item.id] !== false) : selection;
  const checking = active && (query.isFetching || query.status === 'loading');
  const failed = active && query.isError;
  const message = unavailable.length
    ? localize('knowledgeAccess.revoked', { names: unavailable.map((item) => item.name).join(', ') })
    : failed ? localize('knowledgeAccess.failed')
      : checking ? localize('knowledgeAccess.checking') : '';
  return { available, message, blocked: active && (checking || failed || unavailable.length > 0),
    checking, failed, retry: query.refetch };
}
