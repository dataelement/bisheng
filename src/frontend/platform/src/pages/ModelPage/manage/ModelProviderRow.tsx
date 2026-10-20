import { Outlined } from "bisheng-icons";
import { Button, Switch, Tag, Tooltip, TooltipProvider } from '@bisheng/ui'

import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table'

export type ManagedModel = {
    id: number
    model_name: string
    model_type: string
    status: number
    online: boolean
    remark?: string
    status_update_time?: string
}

export type ModelProvider = {
    id: number
    name: string
    models: ManagedModel[]
    is_root_shared_readonly?: boolean
    tenant_name?: string
}

interface ModelProviderRowProps {
    data: ModelProvider
    canManage: boolean
    probing: boolean
    onModel: (id: number) => void
    onToggle: (modelId: number, online: boolean) => Promise<boolean>
    onVerify: (modelId: number) => Promise<void>
}

interface ModelRowProps extends Pick<ModelProviderRowProps, 'probing' | 'onToggle' | 'onVerify'> {
    model: ManagedModel
    canEdit: boolean
}

function ModelRow({ model, canEdit, probing, onToggle, onVerify }: ModelRowProps) {
    const { t } = useTranslation()
    const [pendingOnline, setPendingOnline] = useState<boolean | null>(null)
    const [verifying, setVerifying] = useState(false)
    const toggleLock = useRef(false)
    const verifyLock = useRef(false)

    const handleToggle = async (online: boolean) => {
        if (toggleLock.current) return
        toggleLock.current = true
        setPendingOnline(online)
        try {
            await onToggle(model.id, online)
        } finally {
            // The caller updates the persisted value only after success. Clearing
            // the optimistic state therefore restores it on a failed request.
            setPendingOnline(null)
            toggleLock.current = false
        }
    }

    const handleVerify = async () => {
        if (verifyLock.current) return
        verifyLock.current = true
        setVerifying(true)
        try {
            await onVerify(model.id)
        } finally {
            setVerifying(false)
            verifyLock.current = false
        }
    }

    return <TableRow>
        <TableCell>{model.model_name}</TableCell>
        <TableCell>{model.model_type}</TableCell>
        <TableCell>
            <div className="flex items-center gap-2">
                {probing && model.status === 2
                    ? <span className="inline-flex items-center gap-1 text-text-3"><Outlined.Loading className="animate-spin size-3" />{t('model.modelStatusChecking')}</span>
                    : <Tag size="small" dot color={model.status === 0 ? 'success' : model.status === 1 ? 'warning' : 'default'}>
                        {t(model.status === 0 ? 'model.available' : model.status === 1 ? 'model.abnormal' : 'model.unknown')}
                    </Tag>}
                {model.status === 1 && model.remark && <Tooltip content={model.remark}>
                    <Button variant="ghost" size="icon" aria-label={model.remark}><Outlined.Question className="size-3.5 text-text-3" /></Button>
                </Tooltip>}
                <Button variant="link" size="sm" loading={verifying} disabled={verifying} onClick={handleVerify}>
                    {t('model.updateStatus')}
                </Button>
            </div>
        </TableCell>
        <TableCell className="text-text-3">{model.status_update_time?.replace('T', ' ') || '—'}</TableCell>
        <TableCell>
            <Switch size="small" aria-label={model.model_name} disabled={!canEdit}
                loading={pendingOnline !== null} checked={pendingOnline ?? model.online}
                onCheckedChange={handleToggle} />
        </TableCell>
    </TableRow>
}

export function ModelProviderRow({ data, canManage, probing, onModel, onToggle, onVerify }: ModelProviderRowProps) {
    const { t } = useTranslation()
    const [expanded, setExpanded] = useState(false)
    const canEdit = canManage && !data.is_root_shared_readonly

    return <TooltipProvider>
        <div className="text-sm bs-table-row">
            <div className="grid grid-cols-2 items-center mt-1 mx-2 min-h-[52px] rounded-sm hover:bg-fill-2">
                <div className="bs-table-td h-full p-2 flex items-center gap-3 font-medium first:rounded-l-md last:rounded-r-md">
                    <Button variant="ghost" aria-label={data.name} aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
                        {expanded ? <Outlined.Down className="size-4" /> : <Outlined.Right className="size-4" />}
                        {data.name}
                    </Button>
                    {data.is_root_shared_readonly && <Tag size="small">
                        {t('model.tenantSharedReadonly', { tenantName: data.tenant_name || 'Root' })}
                    </Tag>}
                </div>
                <div className="bs-table-td h-full p-2 flex items-center justify-end first:rounded-l-md last:rounded-r-md">
                    <Button variant="link" disabled={!canEdit} onClick={() => onModel(data.id)}>{t('model.modelConfiguration')}</Button>
                </div>
            </div>
            {expanded && <div className="px-12 py-2">
                {/* The shared library does not yet ship a finalized table. */}
                <Table>
                    <TableHeader><TableRow>
                        <TableHead className="w-[200px]">{t('model.modelName')}</TableHead>
                        <TableHead className="w-[200px] min-w-[100px]">{t('model.modelType')}</TableHead>
                        <TableHead className="min-w-[240px]">{t('model.status')}</TableHead>
                        <TableHead className="w-[180px] min-w-[140px]">{t('model.statusUpdateTime')}</TableHead>
                        <TableHead className="w-[100px] min-w-[100px]">{t('model.onlineOfflineOperation')}</TableHead>
                    </TableRow></TableHeader>
                    <TableBody>
                        {data.models.map(model => <ModelRow key={model.id} model={model} canEdit={canEdit}
                            probing={probing} onToggle={onToggle} onVerify={onVerify} />)}
                        {!data.models.length && <TableRow><TableCell colSpan={5} className="text-center text-text-3">{t('model.empty')}</TableCell></TableRow>}
                    </TableBody>
                </Table>
            </div>}
        </div>
    </TooltipProvider>
}
