import type { HostedAppAction } from '@/controllers/API/hostedApp'

/** Server-derived actions only; missing projections fail closed. */
export function appActionState(actions: readonly HostedAppAction[] | undefined) {
  const has = (action: HostedAppAction) => Boolean(actions?.includes(action))
  return { management: has('edit') || has('publish') || has('unpublish') || has('delete') || has('manage_permission'),
    edit: has('edit'), publish: has('publish'), unpublish: has('unpublish'),
    delete: has('delete'), managePermission: has('manage_permission'),
    rebuild: has('edit') && has('publish') }
}
