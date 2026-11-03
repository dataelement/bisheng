import { deleteAppSecret, getAppSecrets, rebuildAppSecrets, saveAppSecret, type SecretRebuildRequest, type AppSecrets } from '@/controllers/API/appSecrets'
import { useCallback, useEffect, useRef, useState } from 'react'

export function useAppSecrets(appId: string) {
  const [busy, setBusy] = useState(false)
  const latestApp = useRef(appId)
  latestApp.current = appId
  // The 130 shell provides react-query v3, while the transplanted hook used
  // TanStack's separate context. Keep this feature on the existing API layer,
  // without a second provider or cache that could retain secret input values.
  const [snapshot, setSnapshot] = useState<{ appId: string; value: AppSecrets } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const requestSeq = useRef(0)
  const mounted = useRef(false)
  const invalidateRequests = useCallback(() => { requestSeq.current += 1 }, [])
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; invalidateRequests() }
  }, [invalidateRequests])
  const refetch = useCallback(async () => {
    if (!appId) return
    const seq = ++requestSeq.current
    setLoading(true)
    try {
      const data = await getAppSecrets(appId)
      if (mounted.current && latestApp.current === appId && requestSeq.current === seq) {
        setSnapshot({ appId, value: data })
        setError(null)
      }
      return data
    } catch (failure) {
      if (mounted.current && latestApp.current === appId && requestSeq.current === seq) setError(failure)
    } finally {
      if (mounted.current && latestApp.current === appId && requestSeq.current === seq) setLoading(false)
    }
  }, [appId])
  useEffect(() => {
    setBusy(false)
    setSnapshot(null)
    setError(null)
    void refetch()
    return invalidateRequests
  }, [refetch, invalidateRequests])
  const data = snapshot?.appId === appId ? snapshot.value : undefined
  const operationStatus = data?.runtime.rebuild_operation?.status
  useEffect(() => {
    if (!['pending', 'running'].includes(operationStatus || '')) return
    const timer = setTimeout(() => { void refetch() }, 2000)
    return () => clearTimeout(timer)
  }, [data, operationStatus, refetch])
  // Secret values remain only on the request stack, never in a mutation cache.
  const save = useCallback(async (name: string, value: string, revision: number) => {
    setBusy(true)
    try {
      return await saveAppSecret(appId, name, value, revision)
    } finally {
      if (mounted.current && latestApp.current === appId) {
        setBusy(false)
        void refetch()
      }
    }
  }, [appId, refetch])
  const remove = useCallback(async (name: string, revision: number) => {
    setBusy(true)
    try { return await deleteAppSecret(appId, name, revision) }
    finally {
      if (mounted.current && latestApp.current === appId) { setBusy(false); void refetch() }
    }
  }, [appId, refetch])
  const rebuild = useCallback(async (body: SecretRebuildRequest) => {
    if (latestApp.current !== appId) return
    setBusy(true)
    try { return await rebuildAppSecrets(appId, body) }
    finally {
      if (mounted.current && latestApp.current === appId) { setBusy(false); void refetch() }
    }
  }, [appId, refetch])
  return { data, loading, error, busy, save, remove, rebuild, refresh: refetch }
}
