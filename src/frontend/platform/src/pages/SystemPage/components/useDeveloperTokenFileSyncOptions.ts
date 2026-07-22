import {
  DeveloperTokenFileSyncOptions,
  getDeveloperTokenFileSyncOptionsApi,
} from "@/controllers/API/developerToken"
import { useCallback, useEffect, useRef, useState } from "react"

interface FileSyncOptionsScope {
  active: boolean
  tenantId: number | null
  userId: number | null
}

export default function useDeveloperTokenFileSyncOptions({
  active,
  tenantId,
  userId,
}: FileSyncOptionsScope) {
  const [options, setOptions] = useState<DeveloperTokenFileSyncOptions | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generationRef = useRef(0)
  const controllerRef = useRef<AbortController | null>(null)

  const load = useCallback(async (keyword?: string) => {
    if (!active || !tenantId || !userId) return
    const generation = generationRef.current
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setLoading(true)
    setError(null)
    try {
      const result = await getDeveloperTokenFileSyncOptionsApi({
        tenant_id: tenantId,
        user_id: userId,
        space_page_size: 200,
        space_keyword: keyword || undefined,
        signal: controller.signal,
      })
      if (
        !controller.signal.aborted
        && generation === generationRef.current
        && result.tenant_id === tenantId
        && result.user_id === userId
      ) {
        setOptions(result)
      }
    } catch {
      if (!controller.signal.aborted && generation === generationRef.current) {
        setError("load_failed")
      }
    } finally {
      if (!controller.signal.aborted && generation === generationRef.current) {
        setLoading(false)
      }
    }
  }, [active, tenantId, userId])

  useEffect(() => {
    generationRef.current += 1
    controllerRef.current?.abort()
    controllerRef.current = null
    setOptions(null)
    setError(null)
    setLoading(false)
    if (active && tenantId && userId) void load()
    return () => controllerRef.current?.abort()
  }, [active, tenantId, userId, load])

  return {
    options,
    loading,
    error,
    searchSpaces: (keyword: string) => load(keyword.trim()),
  }
}
