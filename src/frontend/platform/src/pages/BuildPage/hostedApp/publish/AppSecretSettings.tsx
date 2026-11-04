import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { generateUUID } from '@/components/bs-ui/utils'
import { getHostedAppErrorMessage } from '@/controllers/API/hostedApp'
import { Button } from '@bisheng/ui'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppSecrets } from '../hooks/useAppSecrets'
import { AppSecretEditor } from './AppSecretEditor'

interface AppSecretSettingsProps {
  appId: string
  canManage: boolean
  canRebuild?: boolean
}
export function AppSecretSettings({ appId, canManage, canRebuild = false }: AppSecretSettingsProps) {
  const { t } = useTranslation()
  const state = useAppSecrets(appId)
  const [editing, setEditing] = useState<string | null | undefined>(undefined)
  const mountedApp = useRef<string | null>(appId)
  useEffect(() => {
    mountedApp.current = appId
    setEditing(undefined)
    return () => { mountedApp.current = null }
  }, [appId])
  const handleRebuild = () => {
    const data = state.data
    if (!data || !data.runtime.running_version_id || data.runtime.route_epoch === null) return
    const request = { request_id: generateUUID(32), expected_version_id: data.runtime.running_version_id,
      expected_config_revision: data.revision, expected_route_epoch: data.runtime.route_epoch, confirm_restart: true as const }
    bsConfirm({ title: t('hostedApp.secrets.rebuild'), desc: t('hostedApp.secrets.rebuildConfirm'),
      onOk: async close => {
        if (mountedApp.current !== appId) { close(); return }
        await state.rebuild(request)
        close()
      } })
  }
  const handleDelete = (name: string) => {
    const revision = state.data?.revision
    if (revision === undefined) return
    bsConfirm({ title: t('hostedApp.secrets.remove'), desc: t('hostedApp.secrets.deleteConfirm', { name }),
      onOk: async close => {
        if (mountedApp.current !== appId) { close(); return }
        await state.remove(name, revision)
        close()
      } })
  }
  const operation = state.data?.runtime.rebuild_operation
  const active = operation && ['pending', 'running'].includes(operation.status)
  return <section className="flex flex-col gap-3" aria-label={t('hostedApp.secrets.title')}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-medium">{t('hostedApp.secrets.title')}</h3>
      <div className="flex flex-wrap gap-2">
        <Button size="small" variant="outlined" onClick={() => { void state.refresh() }} disabled={state.busy}>{t('hostedApp.secrets.refresh')}</Button>
        {canManage && <Button size="small" variant="outlined" onClick={() => setEditing(null)} disabled={state.busy || editing !== undefined}>{t('hostedApp.secrets.add')}</Button>}
      </div>
    </div>
    <p className="text-xs text-muted-foreground">{t('hostedApp.secrets.saveHint')}</p>
    {state.loading && <p className="text-sm">{t('hostedApp.secrets.loading')}</p>}
    {!!state.error && <p role="alert" className="text-sm text-muted-foreground">{getHostedAppErrorMessage(state.error) || t('hostedApp.secrets.loadFailed')}</p>}
    {state.data && <>
      {!state.data.items.length && <p className="text-sm text-muted-foreground">{t('hostedApp.secrets.empty')}</p>}
      {state.data.items.map(item => <div key={item.name} className="flex flex-wrap items-center justify-between gap-2 border-b py-2">
        <div className="min-w-0 text-sm"><span className="break-all font-mono">{item.name}</span>
          <span className="ml-3 text-muted-foreground">{item.present ? (canManage ? item.mask : t('hostedApp.secrets.present')) : t('hostedApp.secrets.missing')}</span>
          <span className="ml-3 text-xs text-muted-foreground">{t(item.approved_reference ? 'hostedApp.secrets.approvedReference' : item.pending_reference ? 'hostedApp.secrets.pendingReference' : 'hostedApp.secrets.unreferenced')}</span>
        </div>
        {canManage && <div className="flex gap-2">
          <Button size="small" variant="text" onClick={() => setEditing(item.name)} disabled={state.busy || editing !== undefined}>{t('hostedApp.secrets.replace')}</Button>
          {(item.present || item.updated_at) && <Button size="small" variant="text" color="danger" onClick={() => handleDelete(item.name)} disabled={state.busy}>{t('hostedApp.secrets.remove')}</Button>}
        </div>}
      </div>)}
      {canManage && editing !== undefined && <AppSecretEditor key={`${appId}:${editing ?? 'new'}`} name={editing} busy={state.busy}
        onClose={() => setEditing(undefined)} onSave={async (name, value) => { await state.save(name, value, state.data!.revision) }} />}
      <p role="status" className="text-sm text-muted-foreground">{t(`hostedApp.secrets.comparison.${state.data.runtime.comparison}`)}</p>
      {!!state.data.runtime.changed_names.length && <p className="break-all text-xs text-muted-foreground">{state.data.runtime.changed_names.join(', ')}</p>}
      {operation && <p role="status" className="text-xs text-muted-foreground">{t(active ? 'hostedApp.secrets.rebuilding' : operation.status === 'completed' ? 'hostedApp.secrets.rebuilt' : 'hostedApp.secrets.rebuildFailed')}</p>}
      {canManage && canRebuild && state.data.runtime.comparison === 'different' && <div><Button size="small" onClick={handleRebuild} disabled={state.busy || Boolean(active)}>{t('hostedApp.secrets.rebuild')}</Button></div>}
    </>}
  </section>
}
