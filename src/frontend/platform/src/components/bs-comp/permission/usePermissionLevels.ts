import { toast } from "@/components/bs-ui/toast/use-toast"
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

const PERMISSION_RELATION: Record<string, string> = {
  view_app: 'can_read',
  use_app: 'can_read',
  edit_app: 'can_edit',
  publish_app: 'can_manage',
  unpublish_app: 'can_manage',
  share_app: 'can_manage',
  delete_app: 'can_delete',
  manage_app_owner: 'can_manage',
  manage_app_manager: 'can_manage',
  manage_app_viewer: 'can_manage',
  view_tool: 'can_read',
  use_tool: 'can_read',
  edit_tool: 'can_edit',
  delete_tool: 'can_delete',
  manage_tool_owner: 'can_manage',
  manage_tool_manager: 'can_manage',
  manage_tool_viewer: 'can_manage',
  view_kb: 'can_read',
  use_kb: 'can_read',
  edit_kb: 'can_edit',
  delete_kb: 'can_delete',
  manage_kb_owner: 'can_manage',
  manage_kb_manager: 'can_manage',
  manage_kb_viewer: 'can_manage',
  view_space: 'can_read',
  edit_space: 'can_edit',
  delete_space: 'can_delete',
  share_space: 'can_manage',
  manage_space_relation: 'can_manage',
  view_folder: 'can_read',
  create_folder: 'can_edit',
  rename_folder: 'can_edit',
  delete_folder: 'can_delete',
  download_folder: 'can_read',
  manage_folder_relation: 'can_manage',
  view_file: 'can_read',
  upload_file: 'can_edit',
  rename_file: 'can_edit',
  delete_file: 'can_delete',
  download_file: 'can_read',
  share_file: 'can_manage',
  manage_file_relation: 'can_manage',
}

export function canManageResource(levels: Record<string, RelationLevel>, id: string | number): boolean {
  const level = levels[String(id)]
  return level === 'owner' || level === 'manager'
}

export function hasPermissionId(
  permissions: Record<string, string[]>,
  id: string | number,
  permissionId: string,
): boolean {
  return permissions[String(id)]?.includes(permissionId) ?? false
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

export function usePermissionIds(
  resourceType: ResourceType,
  resourceIds: string[],
  permissionIds: string[],
): { permissions: Record<string, string[]>; loading: boolean } {
  const { user } = useContext(userContext)
  const [permissions, setPermissions] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!resourceIds.length || !permissionIds.length) {
      abortRef.current?.abort()
      setPermissions({})
      return
    }

    if (user?.role === 'admin') {
      const adminPermissions: Record<string, string[]> = {}
      for (const id of resourceIds) {
        adminPermissions[id] = [...permissionIds]
      }
      setPermissions(adminPermissions)
      setLoading(false)
      return
    }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)

    let notifiedError = false
    const notifyErrorOnce = (error: unknown) => {
      if (error == null || notifiedError || controller.signal.aborted || (error as any)?.code === "ERR_CANCELED") return
      notifiedError = true
      toast({
        title: '提示',
        variant: 'error',
        description: typeof error === 'string' && error ? error : '权限校验失败，请稍后重试',
      })
    }

    const resolvePermissions = async (resourceId: string): Promise<[string, string[]]> => {
      const allowedPermissions: string[] = []
      for (const permissionId of permissionIds) {
        if (controller.signal.aborted) return [resourceId, allowedPermissions]
        try {
          const res = await checkPermission(
            resourceType,
            resourceId,
            PERMISSION_RELATION[permissionId] || 'can_read',
            permissionId,
          )
          if (res?.allowed) allowedPermissions.push(permissionId)
        } catch (error) {
          // Keep permission checks best-effort for UI gating; backend still enforces.
          notifyErrorOnce(error)
        }
      }
      return [resourceId, allowedPermissions]
    }

    Promise.allSettled(resourceIds.map(resolvePermissions)).then((results) => {
      if (controller.signal.aborted) return

      const newPermissions: Record<string, string[]> = {}
      for (const result of results) {
        if (result.status === 'fulfilled') {
          const [id, ids] = result.value
          if (ids.length) newPermissions[id] = ids
        }
      }
      setPermissions(newPermissions)
      setLoading(false)
    })

    return () => { controller.abort() }
  }, [resourceType, resourceIds.join(','), permissionIds.join(','), user?.role])

  return { permissions, loading }
}
