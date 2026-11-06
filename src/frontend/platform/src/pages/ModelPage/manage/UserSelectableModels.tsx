import { Button } from "@bisheng/ui";
import { Input } from "@bisheng/ui";
import { Switch } from "@bisheng/ui";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table'
import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ModelAccessDialog, type DshAccessModel } from './dsh/ModelAccessDialog'
import { ModelMultiplierInput } from './dsh/ModelMultiplierInput'
import { ModelVisionSwitch } from './dsh/ModelVisionSwitch'
import type { ConfiguredUserModel, ModelServer } from './userModelMetadata'

interface UserSelectableModelsProps {
    data: ModelServer[]
    configuredModels: ConfiguredUserModel[]
    enterpriseEnabled: boolean
    disabled: boolean
    onMetadataChange: (model: { id: number; model_name: string }, changes: Pick<ConfiguredUserModel, 'displayName' | 'visual'>) => void
}

export function UserSelectableModels({ data, configuredModels, enterpriseEnabled, disabled, onMetadataChange }: UserSelectableModelsProps) {
    const { t } = useTranslation('model')
    const [selected, setSelected] = useState<DshAccessModel | null>(null)
    const [savingRates, setSavingRates] = useState<Set<number>>(() => new Set())
    const handleRateSaving = useCallback((modelId: number, saving: boolean) => {
        setSavingRates(current => {
            const next = new Set(current)
            if (saving) next.add(modelId); else next.delete(modelId)
            return next
        })
    }, [])
    const models = useMemo(() => data.flatMap(server => server.models
        .filter(model => model.id > 0 && model.online && model.model_type === 'llm')
        .map(model => ({ ...model, provider: server.name }))), [data])

    return <section className="space-y-4">
        <div>
            <h3 className="text-sm font-medium">{t('model.userSelectableModels')}</h3>
            <p className="mt-1 text-xs text-muted-foreground">{t('model.userSelectableModelsHelp')}</p>
        </div>
        <div className="overflow-x-auto rounded-lg border bg-background">
            <Table className="min-w-[1100px] table-fixed">
                <TableHeader><TableRow>
                    <TableHead className="w-[28%]">{t('model.modelName')}</TableHead>
                    <TableHead className="w-[14%]">{t('model.serviceProvider')}</TableHead>
                    <TableHead>{t('model.displayName')}</TableHead>
                    <TableHead className="w-32">{t('model.supportsImages')}</TableHead>
                    {enterpriseEnabled && <TableHead className="w-44">{t('dsh.unified.multiplier', { ns: 'bs' })}</TableHead>}
                    {enterpriseEnabled && <TableHead className="w-32 text-left">{t('model.visibilityScope')}</TableHead>}
                </TableRow></TableHeader>
                <TableBody>{models.map(model => {
                    const config = configuredModels.find(row => String(row.id) === String(model.id))
                    return <TableRow key={model.id}>
                        <TableCell className="min-w-40 max-w-72 break-words font-medium">{model.model_name}</TableCell>
                        <TableCell className="min-w-28">{model.provider}</TableCell>
                        <TableCell className="min-w-44">
                            <Input aria-label={`${t('model.displayName')} · ${model.model_name}`}
                                value={config?.displayName ?? ''} placeholder={model.model_name} disabled={disabled}
                                onChange={event => onMetadataChange(model, { displayName: event.target.value })} />
                        </TableCell>
                        <TableCell>{enterpriseEnabled ? <ModelVisionSwitch modelId={model.id} /> :
                            <Switch aria-label={`${t('model.supportsImages')} · ${model.model_name}`} checked={!!config?.visual}
                                disabled={disabled} onCheckedChange={visual => onMetadataChange(model, { visual })} />}</TableCell>
                        {enterpriseEnabled && <TableCell><ModelMultiplierInput modelId={model.id} modelName={model.model_name} onSavingChange={handleRateSaving} /></TableCell>}
                        {enterpriseEnabled && <TableCell className="text-left">
                            <Button variant="link" className="whitespace-nowrap px-0" disabled={savingRates.has(model.id)}
                                onClick={() => setSelected({ id: model.id, name: config?.displayName?.trim() || model.model_name })}>
                                {t('model.configureVisibility')}
                            </Button>
                        </TableCell>}
                    </TableRow>
                })}</TableBody>
            </Table>
            {!models.length && <p className="px-6 py-12 text-center text-sm text-muted-foreground">{t('model.noOnlineDshModels')}</p>}
        </div>
        <ModelAccessDialog model={selected} onClose={() => setSelected(null)} />
    </section>
}
