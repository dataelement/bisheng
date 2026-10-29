import { Button } from "@bisheng/ui";
import { Input } from "@bisheng/ui";
import { getModelVisibility, saveModelVisibility } from '@/controllers/API/dshUnified'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { Check, Loader2, RotateCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface ModelMultiplierInputProps {
    modelId: number
    modelName: string
    onSavingChange: (modelId: number, saving: boolean) => void
}

export function ModelMultiplierInput({ modelId, modelName, onSavingChange }: ModelMultiplierInputProps) {
    const { t } = useTranslation()
    const [draft, setDraft] = useState('')
    const [confirmed, setConfirmed] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [saved, setSaved] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [revision, setRevision] = useState(0)
    const pending = useRef(false)
    const label = `${t('dsh.unified.multiplier')} · ${modelName}`
    const valid = /^(0|[1-9][0-9]{0,3})(\.[0-9]{1,2})?$/.test(draft)
        && Number(draft) >= 0.01 && Number(draft) <= 1000

    useEffect(() => {
        const abort = new AbortController()
        setLoading(true)
        setConfirmed(null)
        setError(null)
        getModelVisibility(modelId, abort.signal).then(policy => {
            if (abort.signal.aborted) return
            const multiplier = policy.credit_multiplier ?? '1'
            setDraft(multiplier)
            setConfirmed(multiplier)
        }).catch(reason => {
            if (!abort.signal.aborted) setError(getDshRequestErrorKey(reason) ?? 'dsh.unavailable')
        }).finally(() => { if (!abort.signal.aborted) setLoading(false) })
        return () => abort.abort()
    }, [modelId, revision])

    const save = async () => {
        if (pending.current || confirmed === null || draft === confirmed) return
        if (!valid) { setError('dsh.unified.multiplierInvalid'); return }
        pending.current = true
        setSaving(true)
        setError(null)
        setSaved(false)
        onSavingChange(modelId, true)
        try {
            // Read current visibility before changing only the rate. The shared
            // policy version rejects concurrent edits between this read and write.
            const policy = await getModelVisibility(modelId)
            const result = await saveModelVisibility(modelId, { ...policy, credit_multiplier: draft })
            const multiplier = result.credit_multiplier ?? draft
            setConfirmed(multiplier)
            setDraft(multiplier)
            setSaved(true)
        } catch (reason) {
            setError(getDshRequestErrorKey(reason) ?? 'dsh.unavailable')
        } finally {
            pending.current = false
            setSaving(false)
            onSavingChange(modelId, false)
        }
    }

    return <div className="min-w-36 max-w-64">
        <div className="flex items-center gap-2">
            <Input aria-label={label} inputMode="decimal" className="h-8 w-24 shrink-0"
                value={draft} disabled={loading || saving || confirmed === null}
                aria-invalid={confirmed !== null && !valid}
                aria-describedby={error ? `model-multiplier-error-${modelId}` : undefined}
                onChange={event => { setDraft(event.target.value); setError(null); setSaved(false) }}
                onBlur={() => { void save() }}
                onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); void save() } }} />
            {(loading || saving) && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label={t(saving ? 'dsh.unified.saving' : 'dsh.loading')} />}
            {saved && !saving && <Check className="size-4 text-green-600" aria-label={t('dsh.unified.saved')} />}
            {error && error !== 'dsh.unified.multiplierInvalid' && <Button variant="text" iconOnly
                aria-label={`${t('dsh.refresh')} · ${modelName}`} disabled={saving}
                onClick={() => { if (confirmed === null) setRevision(old => old + 1); else void save() }}>
                <RotateCw className="size-4" />
            </Button>}
        </div>
        {error && <p id={`model-multiplier-error-${modelId}`} role="alert" className="mt-1 text-xs text-destructive">{t(error)}</p>}
    </div>
}
