import { Button } from '@/components/bs-ui/button'
import { Checkbox } from '@/components/bs-ui/checkBox'
import { Input } from '@/components/bs-ui/input'
import { TableCell, TableRow } from '@/components/bs-ui/table'
import {
    getDshModelPolicy,
    isDshRequestRejected,
    saveDshPolicy,
} from '@/controllers/API/dsh'
import type {
    DshModelAccessUser,
    DshOperation,
    DshOperationRef,
} from '@/types/dsh'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface ModelAccessRowProps {
    user: DshModelAccessUser
    modelId: number
    tenantId: number
    operations: Record<string, DshOperation>
    unresolved?: DshOperationRef
    rejectedOperationIds?: string[]
    onOperation: (
        userId: number,
        reference: DshOperationRef,
        result?: DshOperation,
    ) => void
}

export function ModelAccessRow({
    user,
    modelId,
    tenantId,
    operations,
    unresolved,
    rejectedOperationIds = [],
    onOperation,
}: ModelAccessRowProps) {
    const { t } = useTranslation()
    const [snapshot, setSnapshot] = useState(user)
    const [allowed, setAllowed] = useState(user.enabled)
    const [limit, setLimit] = useState(
        String(user.monthly_token_limit),
    )
    const [operationId, setOperationId] = useState(
        user.pending_operation_id ?? unresolved?.operation_id ?? null,
    )
    const [rejected, setRejected] = useState(false)
    const [error, setError] = useState(false)
    const [refreshing, setRefreshing] = useState(false)
    const lock = useRef(false)
    const refreshAbort = useRef<AbortController | null>(null)
    useEffect(() => () => refreshAbort.current?.abort(), [])
    useEffect(() => {
        if (user.pending_operation_id)
            onOperation(user.user_id, {
                operation_id: user.pending_operation_id,
                tenant_id: String(tenantId),
                model_id: modelId,
            })
    }, [user.pending_operation_id, user.user_id, tenantId, modelId, onOperation])
    const operation = operationId ? operations[operationId] : undefined
    const terminal =
        operation && ['SUCCEEDED', 'FAILED'].includes(operation.status)
    const operationRejected = rejected || (!!operationId && rejectedOperationIds.includes(operationId))
    const pending = !!operationId && !terminal && !operationRejected
    const stale = operationRejected || !!terminal
    const valid =
        !allowed || (/^\d+$/.test(limit) && Number.isSafeInteger(Number(limit)))
    const dirty =
        allowed !== snapshot.enabled ||
        (allowed && Number(limit) !== snapshot.monthly_token_limit)

    async function handleSave() {
        if (!valid || !dirty || lock.current || pending || stale || refreshing)
            return
        lock.current = true
        setError(false)
        const id = crypto.randomUUID()
        setOperationId(id)
        const body = {
            operation_id: id,
            expected_version: snapshot.version,
            enabled: allowed,
            monthly_token_limit: allowed ? Number(limit) : 0,
        }
        const reference: DshOperationRef = {
            operation_id: id,
            tenant_id: String(tenantId),
                model_id: modelId,
        }
        reference.retry = async () => {
            try {
                onOperation(
                    user.user_id,
                    reference,
                    await saveDshPolicy(
                        String(user.user_id),
                        modelId,
                        String(tenantId),
                        body,
                    ),
                )
            } catch (failure) {
                setError(true)
                if (isDshRequestRejected(failure)) {
                    setRejected(true)
                    setOperationId(null)
                    onOperation(user.user_id, { ...reference, rejected: true })
                }
            }
        }
        onOperation(user.user_id, reference)
        try {
            await reference.retry()
        } finally {
            lock.current = false
        }
    }

    async function handleRefresh() {
        if (pending || refreshing) return
        const abort = new AbortController()
        refreshAbort.current?.abort()
        refreshAbort.current = abort
        setRefreshing(true)
        try {
            const policy = await getDshModelPolicy(
                String(user.user_id),
                modelId,
                String(tenantId),
                abort.signal,
            )
            if (abort.signal.aborted) return
            setSnapshot({
                ...user,
                enabled: policy.enabled,
                monthly_token_limit: policy.monthly_token_limit,
                version: policy.version,
                pending_operation_id: policy.pending_operation_id ?? null,
            })
            setAllowed(policy.enabled)
            setLimit(String(policy.monthly_token_limit))
            setOperationId(policy.pending_operation_id ?? null)
            if (policy.pending_operation_id)
                onOperation(user.user_id, {
                    operation_id: policy.pending_operation_id,
                    tenant_id: String(tenantId),
                model_id: modelId,
                })
            setRejected(false)
            setError(false)
        } catch {
            if (!abort.signal.aborted) setError(true)
        } finally {
            if (!abort.signal.aborted) setRefreshing(false)
        }
    }

    return (
        <TableRow>
            <TableCell>{user.user_name}</TableCell>
            <TableCell>
                <Checkbox
                    aria-label={t('dsh.allowUser', { name: user.user_name })}
                    checked={allowed}
                    disabled={pending || stale || refreshing}
                    onCheckedChange={(checked) => setAllowed(checked === true)}
                />
            </TableCell>
            <TableCell>
                <Input
                    className="w-40"
                    aria-label={t('dsh.userMonthlyLimit', {
                        name: user.user_name,
                    })}
                    inputMode="numeric"
                    value={allowed ? limit : ''}
                    disabled={!allowed || pending || stale || refreshing}
                    onChange={(event) => setLimit(event.target.value)}
                />
            </TableCell>
            <TableCell>
                <div className="flex gap-2">
                    <Button
                        size="sm"
                        disabled={
                            !dirty || !valid || pending || stale || refreshing
                        }
                        onClick={handleSave}
                    >
                        {t('dsh.save')}
                    </Button>
                    {stale && (
                        <Button
                            size="sm"
                            variant="outline"
                            disabled={refreshing}
                            onClick={handleRefresh}
                        >
                            {t('dsh.refresh')}
                        </Button>
                    )}
                </div>
                {pending && <p role="status">{t('dsh.PROCESSING')}</p>}
                {terminal && (
                    <p role="status">{t(`dsh.${operation.status}`)}</p>
                )}
                {stale && (
                    <p className="text-xs text-muted-foreground">
                        {t('dsh.reloadPolicy')}
                    </p>
                )}
                {error && (
                    <p role="alert">
                        {t(rejected ? 'dsh.rejected' : 'dsh.saveUncertain')}
                    </p>
                )}
            </TableCell>
        </TableRow>
    )
}
