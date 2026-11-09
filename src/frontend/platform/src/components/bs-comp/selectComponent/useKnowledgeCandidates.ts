import { useInfiniteQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { readFileLibDatabase } from '@/controllers/API';
import { listVisibleSpaces } from '@/controllers/API/knowledgeSpace';
import { managementRequestScope } from '@/controllers/managementScope';
import { showApiError } from '@/controllers/request';
import { useKnowledgePageScope } from '@/hooks/useKnowledgePageScope';

/** Candidate absence never changes or classifies a saved reference. */
export function useKnowledgeCandidates(kind: 'space' | 'qa', enabled = true) {
    const { scopes } = useKnowledgePageScope();
    const scope = scopes?.ordinary;
    const pin = managementRequestScope();
    const [keyword, setKeyword] = useState('');
    const query = useInfiniteQuery({
        queryKey: ['reference-candidates', scope?.identityKey, scope?.tenantId, scope?.managementTenantId, pin, kind, keyword],
        enabled: enabled && !!scope,
        cacheTime: 0,
        queryFn: async ({ pageParam = null }) => {
            if (managementRequestScope() !== pin) throw new Error('management_scope_changed');
            const result = kind === 'space'
                ? await listVisibleSpaces({ cursor: pageParam, page_size: 60, keyword })
                : await readFileLibDatabase({ cursor: pageParam, pageSize: 60, name: keyword, type: 1, action: 'visible' });
            if (managementRequestScope() !== pin) throw new Error('management_scope_changed');
            return result;
        },
        getNextPageParam: page => page.next_cursor ?? undefined,
        onError: showApiError,
    });
    const items = useMemo(() => scope ? (query.data?.pages.flatMap(page => page.data) ?? [])
        .filter(item => item.id != null && item.id !== '') : [], [scope, query.data]);
    const options = items.map(item => ({ value: item.id as string | number, label: item.name as string, type: kind }));
    return {
        options,
        items,
        scopeKey: scope ? JSON.stringify([scope.identityKey, scope.tenantId, scope.managementTenantId, pin]) : null,
        error: query.error,
        loaded: query.data !== undefined,
        hasMore: query.hasNextPage,
        retry: () => { if (scope) void query.refetch(); },
        search: setKeyword,
        refresh: () => { setKeyword(''); if (scope) void query.refetch(); },
        loadMore: () => { if (query.hasNextPage && !query.isFetching) void query.fetchNextPage(); },
        loading: query.isInitialLoading,
        loadingMore: query.isFetchingNextPage,
    };
}
