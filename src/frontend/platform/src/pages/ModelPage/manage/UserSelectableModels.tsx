import { Button } from "@bisheng/ui";
import { Input } from "@bisheng/ui";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table'
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { BaseModelPicker } from './dsh/BaseModelPicker'
import { ModelAccessDialog, type DshAccessModel } from './dsh/ModelAccessDialog'
import { ModelPriceDialog, type PricedModel } from './dsh/ModelPriceDialog'
import { CreditRatioCell, PriceSummaryCell } from './dsh/ModelPricingCells'
import { ModelVisionSwitch } from './dsh/ModelVisionSwitch'
import { useCreditSettings, useModelPricingRows } from './dsh/useCreditPricing'
import { ModelFieldHint } from './ModelFieldHint'
import type { ConfiguredUserModel, ModelServer } from './userModelMetadata'
import { getModelVisionRows, type ModelVisionRow } from '@/controllers/API/modelPricing'
import { managementRequestScope } from '@/controllers/managementScope'

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
    const [priced, setPriced] = useState<PricedModel | null>(null)
    const pricing = useModelPricingRows(enterpriseEnabled)
    const { settings } = useCreditSettings(enterpriseEnabled)
    const models = useMemo(() => data.flatMap(server => server.models
        .filter(model => model.id > 0 && model.online && model.model_type === 'llm')
        .map(model => {
            const config = configuredModels.find(row => String(row.id) === String(model.id))
            return { ...model, provider: server.name, providerType: server.type, config, label: config?.displayName?.trim() || model.model_name }
        })), [data, configuredModels])
    const modelIds = useMemo(() => models.map(model => model.id), [models])
    const vision = useQuery({
        queryKey: ['model-vision-settings', managementRequestScope(), modelIds],
        queryFn: async ({ signal }) => {
            const rows: ModelVisionRow[] = []
            for (let start = 0; start < modelIds.length; start += 100) {
                rows.push(...await getModelVisionRows(modelIds.slice(start, start + 100), signal))
            }
            return new Map(rows.map(row => [row.model_id, row]))
        },
        enabled: modelIds.length > 0,
        retry: false, cacheTime: 0, refetchOnWindowFocus: false,
    })

    return <section className="space-y-4">
        <div>
            <h3 className="text-sm font-medium">{t('model.userSelectableModels')}</h3>
            {/* Visibility is a platform setting; only credits need the desktop module. */}
            <p className="mt-1 text-xs text-muted-foreground">{t(enterpriseEnabled ? 'model.userSelectableModelsHelp' : 'model.userSelectableModelsHelpBasic')}</p>
        </div>
        {enterpriseEnabled && <BaseModelPicker models={models} rows={pricing.data} />}
        {vision.isError && <p role="alert" className="text-sm">
            {t('model.visionReadFailed')}
            <Button variant="link" size="small" onClick={() => void vision.refetch()}>{t('model.retry')}</Button>
        </p>}
        {enterpriseEnabled && pricing.isError && <p role="alert" className="flex items-center gap-2 text-sm">
            {t('dsh.pricing.unavailable', { ns: 'bs' })}
            <Button variant="link" size="small" className="h-auto px-0" onClick={() => void pricing.refetch()}>
                {t('dsh.pricing.refresh', { ns: 'bs' })}
            </Button>
        </p>}
        <div className="overflow-x-auto rounded-lg border bg-background">
            <Table className={`${enterpriseEnabled ? 'min-w-[1120px]' : 'min-w-[900px]'} table-fixed`}>
                <TableHeader><TableRow>
                    <TableHead className="w-[22%]">{t('model.modelName')}</TableHead>
                    <TableHead className="w-[12%]">{t('model.serviceProvider')}</TableHead>
                    <TableHead>{t('model.displayName')}</TableHead>
                    <TableHead className="w-28">{t('model.supportsImages')}</TableHead>
                    {enterpriseEnabled && <TableHead className="w-32">
                        <span className="inline-flex items-center">
                            {t('dsh.pricing.ratio', { ns: 'bs' })}
                            <ModelFieldHint className="ml-1" content={t('dsh.pricing.ratioHelp', { ns: 'bs' })} />
                        </span>
                    </TableHead>}
                    {enterpriseEnabled && <TableHead className="w-52">{t('dsh.pricing.price', { ns: 'bs' })}</TableHead>}
                    <TableHead className="w-28 text-left">{t('model.visibilityScope')}</TableHead>
                </TableRow></TableHeader>
                <TableBody>{models.map(model => {
                    const row = pricing.data?.get(model.id)
                    return <TableRow key={model.id}>
                        <TableCell className="min-w-40 max-w-72 break-words font-medium">{model.model_name}</TableCell>
                        <TableCell className="min-w-28">{model.provider}</TableCell>
                        <TableCell className="min-w-44">
                            <Input aria-label={`${t('model.displayName')} · ${model.model_name}`}
                                value={model.config?.displayName ?? ''} placeholder={model.model_name} disabled={disabled}
                                onChange={event => onMetadataChange(model, { displayName: event.target.value })} />
                        </TableCell>
                        <TableCell><ModelVisionSwitch modelId={model.id} row={vision.data?.get(model.id)}
                            onSaved={() => vision.refetch()} /></TableCell>
                        {enterpriseEnabled && <TableCell><CreditRatioCell row={row} /></TableCell>}
                        {enterpriseEnabled && <TableCell>
                            <PriceSummaryCell row={row} modelName={model.label} onEdit={() => {
                                if (row) setPriced({ id: model.id, name: model.label, modelName: model.model_name, providerType: model.providerType, row })
                            }} />
                        </TableCell>}
                        <TableCell className="text-left">
                            <Button variant="link" className="whitespace-nowrap px-0"
                                onClick={() => setSelected({ id: model.id, name: model.label })}>
                                {t('model.configureVisibility')}
                            </Button>
                        </TableCell>
                    </TableRow>
                })}</TableBody>
            </Table>
            {!models.length && <p className="px-6 py-12 text-center text-sm text-muted-foreground">{t('model.noOnlineDshModels')}</p>}
        </div>
        <ModelAccessDialog model={selected} onClose={() => setSelected(null)} />
        <ModelPriceDialog model={priced} settings={settings.data} onClose={() => setPriced(null)} />
    </section>
}
