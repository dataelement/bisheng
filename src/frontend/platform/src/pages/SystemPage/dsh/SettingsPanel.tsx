import { Button } from '@/components/bs-ui/button'
import { Input } from '@/components/bs-ui/input'
import { Switch } from '@/components/bs-ui/switch'
import { saveDshManagementSettings, type DshManagementSettings } from '@/controllers/API/dshSettings'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface SettingsPanelProps {
    settings: DshManagementSettings
    canEdit: boolean
}

export function SettingsPanel({ settings, canEdit }: SettingsPanelProps) {
    const { t } = useTranslation()
    const [enabled, setEnabled] = useState(settings.enabled)
    const [download, setDownload] = useState(settings.download_url ?? '')
    const [saving, setSaving] = useState(false)
    const [status, setStatus] = useState<'saved' | 'error' | null>(null)
    const lock = useRef(false)
    const dirty = useRef(false)
    useEffect(() => {
        if (!dirty.current) {
            setEnabled(settings.enabled)
            setDownload(settings.download_url ?? '')
        }
    }, [settings.enabled, settings.download_url])
    async function handleSave() {
        if (lock.current || !canEdit) return
        lock.current = true
        setSaving(true)
        setStatus(null)
        try {
            const result = await saveDshManagementSettings({ enabled, download_url: download.trim() || null })
            setEnabled(result.enabled)
            setDownload(result.download_url ?? '')
            dirty.current = false
            setStatus('saved')
        } catch {
            setStatus('error')
        } finally {
            lock.current = false
            setSaving(false)
        }
    }
    return <section className="space-y-4 rounded-lg border p-4">
        <h3 className="font-semibold">{t('dsh.accessSettings')}</h3>
        <p className="text-sm text-muted-foreground">{t('dsh.businessSwitchHelp')}</p>
        <div className="flex items-center gap-3">
            <Switch aria-label={t('dsh.businessEnabled')} checked={enabled} disabled={!canEdit || saving}
                onCheckedChange={(value) => { dirty.current = true; setEnabled(value); setStatus(null) }} />
            <span>{t(enabled ? 'dsh.businessOn' : 'dsh.businessOff')}</span>
        </div>
        <label className="block space-y-2">
            <span>{t('dsh.downloadAddress')}</span>
            <Input value={download} disabled={!canEdit || saving}
                onChange={(event) => { dirty.current = true; setDownload(event.target.value); setStatus(null) }} />
        </label>
        <p className="text-sm text-muted-foreground">{t('dsh.downloadAddressHelp')}</p>
        {canEdit ? <Button disabled={saving} onClick={handleSave}>{t('dsh.saveSettings')}</Button>
            : <p>{t('dsh.settingsAdminOnly')}</p>}
        {status && <p role={status === 'error' ? 'alert' : 'status'}>{t(status === 'saved' ? 'dsh.settingsSaved' : 'dsh.settingsSaveFailed')}</p>}
        <p className="text-sm text-muted-foreground">{t('dsh.licenseDeploymentOnly')}</p>
    </section>
}
