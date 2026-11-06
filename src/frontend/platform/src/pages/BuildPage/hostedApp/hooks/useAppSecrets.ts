import { deleteAppSecret, getAppSecrets, rebuildAppSecrets, saveAppSecret, type SecretRebuildRequest } from '@/controllers/API/appSecrets'
import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

export function useAppSecrets(appId: string) {
  const [busy, setBusy] = useState(false)
  const latestApp = useRef(appId)
  latestApp.current = appId
  const query = useQuery({
    queryKey: ['hosted-app-secrets', appId],
    queryFn: () => getAppSecrets(appId),
    enabled: Boolean(appId),
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: data => data?.runtime.rebuild_operation && ['pending', 'running'].includes(data.runtime.rebuild_operation.status) ? 2000 : false,
  })
  const { refetch } = query
  useEffect(() => { setBusy(false) }, [appId])
  // Secret values remain only on the request stack, never in a mutation cache.
  const save = useCallback(async (name: string, value: string, revision: number) => {
    setBusy(true)
    try {
      return await saveAppSecret(appId, name, value, revision)
    } finally {
      if (latestApp.current === appId) {
        setBusy(false)
        void refetch()
      }
    }
  }, [appId, refetch])
  const remove = useCallback(async (name: string, revision: number) => {
    setBusy(true)
    try { return await deleteAppSecret(appId, name, revision) }
    finally {
      if (latestApp.current === appId) { setBusy(false); void refetch() }
    }
  }, [appId, refetch])
  const rebuild = useCallback(async (body: SecretRebuildRequest) => {
    if (latestApp.current !== appId) return
    setBusy(true)
    try { return await rebuildAppSecrets(appId, body) }
    finally {
      if (latestApp.current === appId) { setBusy(false); void refetch() }
    }
  }, [appId, refetch])
  return { data: query.data, loading: query.isInitialLoading, error: query.error, busy, save, remove, rebuild, refresh: query.refetch }
}
