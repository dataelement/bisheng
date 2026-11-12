import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getRuntimeAuditExport, getRuntimeAuditRecords } from '@/controllers/API/runtimeAudit'
import type { RuntimeAuditFilters, RuntimeAuditKind } from '@/controllers/API/runtimeAudit'

// Keep explicit searches distinct even after switching audit views.
let searchSequence = 0

export function useRuntimeAudit(kind: RuntimeAuditKind, filters: RuntimeAuditFilters, scopeKey: string) {
  const selection = JSON.stringify([scopeKey, kind, filters])
  const [paging, setPaging] = useState({ selection, cursors: [undefined as string | undefined], index: 0 })
  const [searchVersion, setSearchVersion] = useState(0)
  const [exportSelection, setExportSelection] = useState<{ selection: string; id: string } | null>(null)
  const current = paging.selection === selection ? paging : { selection, cursors: [undefined], index: 0 }
  const resetPage = () => setPaging({ selection, cursors: [undefined], index: 0 })
  const query = useQuery({
    queryKey: ['runtime-audit', selection, searchVersion, current.cursors[current.index]],
    queryFn: () => getRuntimeAuditRecords(kind, filters, current.cursors[current.index]),
    keepPreviousData: false,
    retry: false,
  })
  const jobId = exportSelection?.selection === selection ? exportSelection.id : null
  const exportQuery = useQuery({
    queryKey: ['runtime-audit-export', selection, jobId],
    queryFn: () => getRuntimeAuditExport(jobId!, filters.tenant_id),
    enabled: !!jobId,
    retry: false,
    refetchInterval: data => data && ['pending', 'running'].includes(data.status) ? 1500 : false,
  })
  return {
    query, exportQuery, jobId, page: current.index + 1,
    setJob: (id: string) => setExportSelection({ selection, id }),
    resetPage,
    reloadFromFirstPage: () => {
      resetPage()
      searchSequence += 1
      setSearchVersion(searchSequence)
    },
    setPage: (page: number) => {
      if (query.isFetching) return
      const index = page - 1
      if (index === current.index + 1 && query.data?.next_cursor) {
        setPaging({ selection, cursors: [...current.cursors.slice(0, index), query.data.next_cursor], index })
      } else if (index === current.index - 1 && index >= 0) {
        setPaging({ ...current, index })
      }
    },
  }
}
