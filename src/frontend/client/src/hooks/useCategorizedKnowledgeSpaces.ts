/**
 * Knowledge spaces grouped the same way the 知识空间 page groups them:
 * 部门知识空间 / 我创建的 / 我加入的, in that fixed order.
 *
 * The grouping rules are NOT re-derived here — they mirror
 * `pages/knowledge/sidebar/KnowledgeSpaceSidebar.tsx`: one endpoint per
 * category, and a department space is subtracted from created / joined so it
 * only ever shows once. Query keys (and the requested sort) match that page's
 * defaults, so opening a picker right after visiting it serves from cache and
 * revalidates in the background instead of blocking on three fresh requests.
 * Display order is re-derived client-side — see compareSpaceName.
 */
import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
    getDepartmentSpacesApi,
    getJoinedSpacesApi,
    getMineSpacesApi,
    SpaceSortType,
    type KnowledgeSpace,
} from '~/api/knowledge';
import useLocalize from './useLocalize';

export type KnowledgeSpaceCategory = 'department' | 'created' | 'joined';

export interface KnowledgeSpaceGroup {
    key: KnowledgeSpaceCategory;
    label: string;
    spaces: KnowledgeSpace[];
}

/**
 * A–Z, ASCII-leading names first, then CJK by pinyin. Kept from the previous
 * flat picker list so intra-group ordering is unchanged.
 */
function compareSpaceName(a: KnowledgeSpace, b: KnowledgeSpace): number {
    const an = (a.name || '').trim();
    const bn = (b.name || '').trim();
    const aIsEn = an.length > 0 && an.charCodeAt(0) < 128;
    const bIsEn = bn.length > 0 && bn.charCodeAt(0) < 128;
    if (aIsEn !== bIsEn) return aIsEn ? -1 : 1;
    return an.localeCompare(bn, aIsEn ? 'en' : 'zh-Hans-u-co-pinyin', {
        sensitivity: 'base',
    });
}

interface Options {
    /** Spaces are only needed while a picker is open — skip the fetch otherwise. */
    enabled?: boolean;
    /** Client-side name filter; empty groups drop out of the result. */
    keyword?: string;
}

export function useCategorizedKnowledgeSpaces({ enabled = true, keyword = '' }: Options = {}) {
    const localize = useLocalize();
    // Must equal the 知识空间 page's default sort or the cache keys diverge.
    const sortBy = SpaceSortType.UPDATE_TIME;

    const departmentQuery = useQuery({
        queryKey: ['knowledgeSpaces', 'department', sortBy],
        queryFn: () => getDepartmentSpacesApi({ order_by: sortBy }),
        enabled,
        refetchOnWindowFocus: false,
    });
    const createdQuery = useQuery({
        queryKey: ['knowledgeSpaces', 'mine', sortBy],
        queryFn: () => getMineSpacesApi({ order_by: sortBy }),
        enabled,
        refetchOnWindowFocus: false,
    });
    const joinedQuery = useQuery({
        queryKey: ['knowledgeSpaces', 'joined', sortBy],
        queryFn: () => getJoinedSpacesApi({ order_by: sortBy }),
        enabled,
        refetchOnWindowFocus: false,
    });
    // Kept as the raw (possibly undefined) query data so they stay referentially
    // stable across renders — defaulting to [] out here would hand the memo below
    // a fresh array every render.
    const departmentData = departmentQuery.data;
    const createdData = createdQuery.data;
    const joinedData = joinedQuery.data;

    /** All three settled once — callers freeze a content-fit popup width on this. */
    const isFetched = departmentQuery.isFetched && createdQuery.isFetched && joinedQuery.isFetched;
    const refetch = useCallback(() => {
        departmentQuery.refetch();
        createdQuery.refetch();
        joinedQuery.refetch();
        // eslint-disable-next-line react-hooks/exhaustive-deps -- refetch fns are stable per query
    }, []);

    const groups = useMemo<KnowledgeSpaceGroup[]>(() => {
        const departmentSpaces = departmentData ?? [];
        const createdSpaces = createdData ?? [];
        const joinedSpaces = joinedData ?? [];
        const departmentIds = new Set(departmentSpaces.map((s) => s.id));
        const kw = keyword.trim().toLowerCase();
        const shape = (spaces: KnowledgeSpace[]) =>
            spaces
                .filter((s) => !kw || s.name?.toLowerCase().includes(kw))
                .sort(compareSpaceName);

        return (
            [
                {
                    key: 'department' as const,
                    label: localize('com_knowledge.department_spaces'),
                    spaces: shape(departmentSpaces),
                },
                {
                    key: 'created' as const,
                    label: localize('com_knowledge.created_by_me'),
                    spaces: shape(createdSpaces.filter((s) => !departmentIds.has(s.id))),
                },
                {
                    key: 'joined' as const,
                    label: localize('com_knowledge.joined_by_me'),
                    spaces: shape(joinedSpaces.filter((s) => !departmentIds.has(s.id))),
                },
            ]
                // A category with nothing to show hides its title too.
                .filter((group) => group.spaces.length > 0)
        );
    }, [departmentData, createdData, joinedData, keyword, localize]);

    return {
        groups,
        isFetching: departmentQuery.isFetching || createdQuery.isFetching || joinedQuery.isFetching,
        isFetched,
        refetch,
    };
}
