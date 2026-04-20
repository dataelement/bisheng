import { userContext } from "@/contexts/userContext"
import { checkPermission } from "@/controllers/API/permission"
import { useContext, useEffect, useRef, useState } from "react"
import { RelationLevel, ResourceType } from "./types"

// Check order: highest to lowest, short-circuit on first allowed
const CHECK_ORDER: Array<{ relation: string; level: RelationLevel }> = [
  { relation: 'owner', level: 'owner' },
  { relation: 'can_manage', level: 'manager' },
  { relation: 'can_edit', level: 'editor' },
  { relation: 'can_read', level: 'viewer' },
]

export function canManageResource(levels: Record<string, RelationLevel>, id: string | number): boolean {
  const level = levels[String(id)]
  return level === 'owner' || level === 'manager'
}

export function usePermissionLevels(
  resourceType: ResourceType,
  resourceIds: string[],
): { levels: Record<string, RelationLevel>; loading: boolean } {
  const { user } = useContext(userContext)
  const [levels, setLevels] = useState<Record<string, RelationLevel>>({})
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!resourceIds.length) {
      abortRef.current?.abort()
      setLevels({})
      return
    }

    // INV-5: Admin shortcircuit — all resources return 'owner'
    if (user?.role === 'admin') {
      const adminLevels: Record<string, RelationLevel> = {}
      for (const id of resourceIds) {
        adminLevels[id] = 'owner'
      }
      setLevels(adminLevels)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)

    const resolveLevel = async (resourceId: string): Promise<[string, RelationLevel | null]> => {
      for (const { relation, level } of CHECK_ORDER) {
        if (controller.signal.aborted) return [resourceId, null]
        try {
          const res = await checkPermission(resourceType, resourceId, relation)
          if (res?.allowed) return [resourceId, level]
        } catch {
          // Network error or abort — skip
        }
      }
      return [resourceId, null]
    }

    Promise.allSettled(resourceIds.map(resolveLevel)).then((results) => {
      if (controller.signal.aborted) return

      const newLevels: Record<string, RelationLevel> = {}
      for (const result of results) {
        if (result.status === 'fulfilled') {
          const [id, level] = result.value
          if (level) newLevels[id] = level
        }
      }
      setLevels(newLevels)
      setLoading(false)
    })

    return () => { controller.abort() }
  }, [resourceType, resourceIds.join(','), user?.role])

  return { levels, loading }
}
