import { Button, Input, Textarea } from '@bisheng/ui'
import { showApiError } from '@/controllers/request'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface AppSecretEditorProps {
  name: string | null
  busy: boolean
  onSave: (name: string, value: string) => Promise<void>
  onClose: () => void
}
export function AppSecretEditor({ name, busy, onSave, onClose }: AppSecretEditorProps) {
  const { t } = useTranslation()
  const id = useId()
  const [draftName, setDraftName] = useState(name ?? '')
  const [value, setValue] = useState('')
  const [uncertain, setUncertain] = useState(false)
  const handleClose = () => { setValue(''); setDraftName(''); onClose() }
  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      await onSave(draftName, value)
      handleClose()
    } catch (error) {
      setUncertain(true)
      showApiError(error)
    }
  }
  return <form onSubmit={handleSave} className="flex flex-col gap-3 rounded-md border p-4">
    <label htmlFor={`${id}-name`} className="text-sm">{t('hostedApp.secrets.name')}</label>
    <Input id={`${id}-name`} value={draftName} onChange={event => setDraftName(event.target.value)} readOnly={name !== null} autoComplete="off" disabled={busy} />
    <label htmlFor={`${id}-value`} className="text-sm">{t('hostedApp.secrets.value')}</label>
    <Textarea id={`${id}-value`} value={value} onChange={event => setValue(event.target.value)} rows={3} autoComplete="off" spellCheck={false} disabled={busy} />
    <p className="text-xs text-muted-foreground">{t('hostedApp.secrets.valueHint')}</p>
    {uncertain && <p role="status" className="text-xs text-muted-foreground">{t('hostedApp.secrets.uncertain')}</p>}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" size="small" disabled={busy || !draftName}>{t('hostedApp.secrets.save')}</Button>
      <Button type="button" size="small" variant="outlined" onClick={handleClose} disabled={busy}>{t('hostedApp.secrets.cancel')}</Button>
    </div>
  </form>
}
