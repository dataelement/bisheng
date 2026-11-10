import { useQuery } from '@tanstack/react-query';
import { getMineSpacesApi, getJoinedSpacesApi, getDepartmentSpacesApi, SpaceSortType } from '~/api/knowledge';

interface SpaceListOptions {
  enabled?: boolean;
  mineOrder?: SpaceSortType;
  joinedOrder?: SpaceSortType;
  departmentOrder?: SpaceSortType;
}

export function useKnowledgeSpaceLists({ enabled = true, mineOrder = SpaceSortType.UPDATE_TIME, joinedOrder = SpaceSortType.UPDATE_TIME, departmentOrder = SpaceSortType.UPDATE_TIME }: SpaceListOptions = {}) {
  const mine = useQuery({ queryKey: ['knowledgeSpaces', 'mine', mineOrder], queryFn: () => getMineSpacesApi({ order_by: mineOrder }), enabled, placeholderData: prev => prev });
  const joined = useQuery({ queryKey: ['knowledgeSpaces', 'joined', joinedOrder], queryFn: () => getJoinedSpacesApi({ order_by: joinedOrder }), enabled, placeholderData: prev => prev });
  const department = useQuery({ queryKey: ['knowledgeSpaces', 'department', departmentOrder], queryFn: () => getDepartmentSpacesApi({ order_by: departmentOrder }), enabled, placeholderData: prev => prev });
  return { mine, joined, department, error: mine.error ?? joined.error ?? department.error,
    retry: () => { void Promise.allSettled([mine.refetch(), joined.refetch(), department.refetch()]); } };
}
