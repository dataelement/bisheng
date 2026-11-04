import { useQuery } from '@tanstack/react-query'
import { getAuditDepartmentsApi } from '@/controllers/API/log'

const KEY = 'audit-departments'

/** Top level + archived list, or a flat search result when `keyword` is set. */
export function useAuditDepartmentRoots(tenantId: number | null | undefined, keyword: string, enabled: boolean) {
  return useQuery({
    queryKey: [KEY, tenantId ?? null, 'roots', keyword],
    queryFn: () => getAuditDepartmentsApi({ tenantId, keyword }),
    enabled,
    retry: false,
    staleTime: 60_000,
  })
}

/** Children of one department, fetched the first time it is expanded. */
export function useAuditDepartmentChildren(tenantId: number | null | undefined, parentId: number, enabled: boolean) {
  return useQuery({
    queryKey: [KEY, tenantId ?? null, 'children', parentId],
    queryFn: () => getAuditDepartmentsApi({ tenantId, parentId }),
    enabled,
    retry: false,
    staleTime: 60_000,
  })
}
