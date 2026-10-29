import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { Button } from "@bisheng/ui";
import { Switch } from "@bisheng/ui";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog'
import {
    getModelVisibility, getPolicySubjects, saveModelVisibility,
    type ModelVisibility, type PolicySubjectOption,
} from '@/controllers/API/dshUnified'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ModelPermissionRoster } from './ModelPermissionRoster'

export type DshAccessModel = { id: number; name: string }
interface ModelAccessDialogProps {
    model: DshAccessModel | null
    onClose: () => void
}

export function ModelAccessDialog({ model, onClose }: ModelAccessDialogProps) {
    const { t } = useTranslation()
    const [value, setValue] = useState<ModelVisibility | null>(null)
    const [options, setOptions] = useState<PolicySubjectOption[]>([])
    const [dirty, setDirty] = useState(false)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [revision, setRevision] = useState(0)
    const modelId = model?.id

    useEffect(() => {
        setValue(null)
        setDirty(false)
        setError(null)
        if (!modelId) return
        const abort = new AbortController()
        Promise.all([getModelVisibility(modelId, abort.signal), getPolicySubjects(abort.signal)])
            .then(([policy, subjects]) => {
                if (abort.signal.aborted) return
                setValue(policy)
                setOptions(subjects)
            })
            .catch(() => { if (!abort.signal.aborted) setError('dsh.unavailable') })
        return () => abort.abort()
    }, [modelId, revision])

    const close = () => {
        if (saving) return
        if (!dirty) { onClose(); return }
        bsConfirm({
            title: t('dsh.discardPolicyEdits'), desc: t('dsh.discardPolicyEditsHelp'),
            okTxt: t('dsh.discardEdits'), onOk(next) { onClose(); next() },
        })
    }
    const save = async () => {
        if (!modelId || !value || saving) return
        setSaving(true)
        setError(null)
        try {
            await saveModelVisibility(modelId, value)
            setDirty(false)
            onClose()
        } catch (reason) {
            setError(getDshRequestErrorKey(reason) ?? 'dsh.unavailable')
        } finally { setSaving(false) }
    }

    return <Dialog open={!!model} onOpenChange={open => { if (!open) close() }}>
        <DialogContent className="flex max-h-[calc(100dvh-48px)] w-[calc(100vw-48px)] max-w-[800px] min-w-0 flex-col gap-0 overflow-y-auto p-5">
            <DialogHeader className="mb-4"><DialogTitle>{t('dsh.unified.visibility')} · {model?.name}</DialogTitle><DialogDescription className="sr-only">{t('dsh.unified.visibilityHelp')}</DialogDescription></DialogHeader>
            {error && <p role="alert">{t(error)}</p>}
            {!value ? <Button variant="outlined" onClick={() => setRevision(old => old + 1)}>
                {t(error ? 'dsh.refresh' : 'dsh.loading')}
            </Button> : <>
                <div className="flex shrink-0 items-center justify-between gap-4 rounded-lg border px-4 py-3">
                    <div className="min-w-0 space-y-1">
                        <label htmlFor="model-visible-to-everyone" className="cursor-pointer text-sm font-medium">{t('dsh.unified.everyoneVisible')}</label>
                        <p id="model-visibility-description" className="text-xs text-muted-foreground">
                            {t(value.everyone ? 'dsh.unified.everyoneVisibleHelp' : 'dsh.unified.selectedVisibleHelp')}
                        </p>
                    </div>
                    <Switch id="model-visible-to-everyone" checked={value.everyone} disabled={saving}
                        aria-describedby="model-visibility-description"
                        onCheckedChange={everyone => { setValue({ ...value, everyone }); setDirty(true) }} />
                </div>
                {!value.everyone && model && <section aria-label={t('dsh.unified.selectedVisible')}
                    className="mt-4 flex h-[clamp(180px,32vh,300px)] shrink-0 flex-col">
                    <ModelPermissionRoster key={model.id} model={model} value={value}
                        options={options} disabled={saving}
                        onChange={next => { setValue(next); setDirty(true) }} />
                </section>}
                <div className="mt-4 flex shrink-0 justify-end gap-2">
                    <Button variant="outlined" onClick={close} disabled={saving}>{t('dsh.unified.cancel')}</Button>
                    <Button onClick={save} disabled={saving || !dirty}>
                        {t(saving ? 'dsh.unified.saving' : 'dsh.unified.save')}
                    </Button>
                </div>
            </>}
        </DialogContent>
    </Dialog>
}
