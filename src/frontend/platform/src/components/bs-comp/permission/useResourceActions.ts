import { toast } from "@/components/bs-ui/toast/use-toast"
import { userContext } from "@/contexts/userContext"
import { getMyResourcePermissionsApi } from "@/controllers/API/permission"
import { useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ResourceType } from "./types"

const ACTION_CACHE_TTL_MS = 60_000

interface ActionCacheEntry {
  expiresAt: number
  actions: string[]
}

interface ActionLoadResult {
  hasError: boolean
  actions: Record<string, string[]>
}

const actionCache = new Map<string, ActionCacheEntry>()
const actionRequests = new Map<string, Promise<string[]>>()

function cacheKey(
  userId: string,
  resourceType: ResourceType,
  resourceId: string,
): string {
  return JSON.stringify([userId, resourceType, resourceId])
}

async function getResourceActionSet(
  userId: string,
  resourceType: ResourceType,
  resourceId: string,
): Promise<string[]> {
  const key = cacheKey(userId, resourceType, resourceId)
  const cached = actionCache.get(key)
  if (cached && cached.expiresAt > Date.now()) return cached.actions
  if (cached) actionCache.delete(key)

  const inFlight = actionRequests.get(key)
  if (inFlight) return inFlight

  const request = getMyResourcePermissionsApi(resourceType, resourceId)
    .then((result) => {
      const actions = Array.from(new Set(result.actions))
      actionCache.set(key, {
        expiresAt: Date.now() + ACTION_CACHE_TTL_MS,
        actions,
      })
      return actions
    })
    .finally(() => {
      actionRequests.delete(key)
    })

  actionRequests.set(key, request)
  return request
}

async function getResourceActions(
  userId: string,
  resourceType: ResourceType,
  resourceIds: string[],
  requestedActions: string[],
): Promise<ActionLoadResult> {
  const actionFilter = new Set(requestedActions)
  const results = await Promise.allSettled(
    resourceIds.map(async (resourceId) => [
      resourceId,
      (await getResourceActionSet(userId, resourceType, resourceId))
        .filter((action) => actionFilter.has(action)),
    ] as const),
  )

  const actions: Record<string, string[]> = {}
  let hasError = false
  for (const result of results) {
    if (result.status === "rejected") {
      hasError = true
      continue
    }
    const [resourceId, allowed] = result.value
    if (allowed.length) actions[resourceId] = allowed
  }
  return { hasError, actions }
}

export function hasResourceAction(
  actions: Record<string, string[]>,
  id: string | number,
  action: string,
): boolean {
  return actions[String(id)]?.includes(action) ?? false
}

export function useResourceActions(
  resourceType: ResourceType,
  resourceIds: string[],
  requestedActions: string[],
): { actions: Record<string, string[]>; loading: boolean } {
  const { user } = useContext(userContext)
  const { t } = useTranslation("permission")
  const translateRef = useRef(t)
  translateRef.current = t
  const [actions, setActions] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(false)
  const userId = user?.user_id == null ? "" : String(user.user_id)
  const resourceIdsKey = resourceIds.join(",")
  const requestedActionsKey = requestedActions.join(",")

  useEffect(() => {
    if (!userId || !resourceIds.length || !requestedActions.length) {
      setActions({})
      setLoading(false)
      return
    }

    if (user?.role === "admin") {
      setActions(Object.fromEntries(
        resourceIds.map((id) => [id, [...requestedActions]]),
      ))
      setLoading(false)
      return
    }

    setLoading(true)
    let disposed = false
    getResourceActions(
      userId,
      resourceType,
      resourceIds,
      requestedActions,
    ).then((result) => {
      if (disposed) return
      setActions(result.actions)
      setLoading(false)
      if (result.hasError) {
        toast({
          title: translateRef.current("dialog.title"),
          variant: "error",
          description: translateRef.current("error.checkFailed"),
        })
      }
    })

    return () => {
      disposed = true
    }
  }, [
    resourceType,
    resourceIdsKey,
    requestedActionsKey,
    user?.role,
    userId,
  ])

  return { actions, loading }
}
