import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getRuntimeAuditExport, getRuntimeAuditRecords } from '@/controllers/API/runtimeAudit'
import type { RuntimeAuditFilters, RuntimeAuditKind } from '@/controllers/API/runtimeAudit'

export function useRuntimeAudit(kind: RuntimeAuditKind, filters: RuntimeAuditFilters, scopeKey: string) {
  const selection = JSON.stringify([scopeKey, kind, filters])
  const [paging, setPaging] = useState({ selection, cursors: [undefined as string | undefined], index: 0 })
  const [exportSelection, setExportSelection] = useState<{ selection: string; id: string } | null>(null)
  const current = paging.selection === selection ? paging : { selection, cursors: [undefined], index: 0 }
  const query = useQuery({
    queryKey: ['runtime-audit', selection, current.cursors[current.index]],
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
    next: () => {
      if (!query.data?.next_cursor) return
      setPaging({ selection, cursors: [...current.cursors.slice(0, current.index + 1), query.data.next_cursor], index: current.index + 1 })
    },
    previous: () => setPaging({ ...current, index: Math.max(0, current.index - 1) }),
  }
}
