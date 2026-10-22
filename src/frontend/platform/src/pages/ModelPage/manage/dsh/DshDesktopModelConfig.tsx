import { Badge } from '@/components/bs-ui/badge'
import { Button } from '@/components/bs-ui/button'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/bs-ui/table'
import { ShieldCheck } from 'lucide-react'
import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ModelAccessDialog, type DshAccessModel } from './ModelAccessDialog'
import { ModelMultiplierInput } from './ModelMultiplierInput'
import { ModelVisionSwitch } from './ModelVisionSwitch'

type ModelServer = {
    id: number
    name: string
    models: Array<{
        id: number
        model_name: string
        model_type: string
        online: boolean
        is_root_shared_readonly?: boolean
    }>
}

export function DshDesktopModelConfig({ data }: { data: ModelServer[] }) {
    const { t } = useTranslation('model')
    const [selected, setSelected] = useState<DshAccessModel | null>(null)
    const [savingRates, setSavingRates] = useState<Set<number>>(() => new Set())
    const onRateSaving = useCallback((modelId: number, saving: boolean) => {
        setSavingRates(current => {
            const next = new Set(current)
            if (saving) next.add(modelId); else next.delete(modelId)
            return next
        })
    }, [])
    const models = useMemo(
        () =>
            data.flatMap((server) =>
                server.models
                    .filter((model) => model.online && model.model_type === 'llm')
                    .map((model) => ({
                        ...model,
                        provider: server.name,
                    })),
            ),
        [data],
    )

    return (
        <div className="space-y-5">
            <div className="overflow-hidden rounded-lg border bg-background">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('model.modelName')}</TableHead>
                            <TableHead>{t('model.serviceProvider')}</TableHead>
                            <TableHead>{t('model.status')}</TableHead>
                            <TableHead>{t('model.supportsImages')}</TableHead>
                            <TableHead>{t('dsh.unified.multiplier', { ns: 'bs' })}</TableHead>
                            <TableHead className="text-right">
                                {t('model.actions')}
                            </TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {models.map((model) => (
                            <TableRow key={model.id}>
                                <TableCell className="font-medium">
                                    {model.model_name}
                                </TableCell>
                                <TableCell>{model.provider}</TableCell>
                                <TableCell>
                                    <Badge
                                        variant="secondary"
                                        className="gap-1 text-green-600"
                                    >
                                        <ShieldCheck className="size-3.5" />
                                        {t('model.available')}
                                    </Badge>
                                </TableCell>
                                <TableCell><ModelVisionSwitch modelId={model.id} /></TableCell>
                                <TableCell><ModelMultiplierInput modelId={model.id} modelName={model.model_name} onSavingChange={onRateSaving} /></TableCell>
                                <TableCell className="text-right">
                                    <Button
                                        variant="link"
                                        disabled={savingRates.has(model.id)}
                                        onClick={() =>
                                            setSelected({
                                                id: model.id,
                                                name: model.model_name,
                                            })
                                        }
                                    >
                                        {t('model.configureDshPermission')}
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
                {!models.length && (
                    <div className="px-6 py-12 text-center text-sm text-muted-foreground">
                        {t('model.noOnlineDshModels')}
                    </div>
                )}
            </div>
            <ModelAccessDialog
                model={selected}
                onClose={() => setSelected(null)}
            />
        </div>
    )
}
