import type { HostedAppAction } from '@/controllers/API/hostedApp'

/** Server-derived actions only; missing projections fail closed. */
export function appActionState(actions: readonly HostedAppAction[] | undefined) {
  const has = (action: HostedAppAction) => Boolean(actions?.includes(action))
  return { management: Boolean(actions?.some(action => action !== 'use')),
    edit: has('edit'), publish: has('publish'), unpublish: has('unpublish'),
    delete: has('delete'), managePermission: has('manage_permission'),
    rebuild: has('edit') && has('publish') }
}
