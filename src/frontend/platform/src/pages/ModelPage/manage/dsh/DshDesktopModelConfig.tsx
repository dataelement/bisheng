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
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ModelAccessDialog, type DshAccessModel } from './ModelAccessDialog'
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
                                <TableCell className="text-right">
                                    <Button
                                        variant="link"
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
