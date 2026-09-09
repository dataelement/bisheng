import { Button } from '@/components/bs-ui/button'
import { getDshOperation } from '@/controllers/API/dsh'
import type { DshOperation, DshOperationRef } from '@/types/dsh'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { dshTime } from './common'

interface OperationStatusProps {
    reference: DshOperationRef
    operation?: DshOperation
    onUpdate: (reference: DshOperationRef, result: DshOperation) => void
}
export function OperationStatus({
    reference,
    operation,
    onUpdate,
}: OperationStatusProps) {
    const { t } = useTranslation()
    const [unavailable, setUnavailable] = useState(false)
    const [retrying, setRetrying] = useState(false)
    const [revision, setRevision] = useState(0)
    const [paused, setPaused] = useState(false)
    const terminal =
        reference.rejected ||
        operation?.status === 'SUCCEEDED' ||
        operation?.status === 'FAILED'
    useEffect(() => {
        if (terminal) return
        const abort = new AbortController()
        let timer: number
        let attempts = 0
        setPaused(false)
        async function poll() {
            try {
                const result = await getDshOperation(
                    reference.operation_id,
                    reference.tenant_id,
                    abort.signal,
                )
                if (abort.signal.aborted) return
                setUnavailable(false)
                onUpdate(
                    {
                        operation_id: reference.operation_id,
                        tenant_id: reference.tenant_id,
                    },
                    result,
                )
                if (['SUCCEEDED', 'FAILED'].includes(result.status)) return
            } catch {
                if (abort.signal.aborted) return
                setUnavailable(true)
            }
            attempts += 1
            if (attempts >= 30) {
                setPaused(true)
                return
            }
            timer = window.setTimeout(
                poll,
                Math.min(1000 * 2 ** Math.min(attempts, 3), 8000),
            )
        }
        void poll()
        return () => {
            abort.abort()
            window.clearTimeout(timer)
        }
    }, [
        reference.operation_id,
        reference.tenant_id,
        terminal,
        revision,
        onUpdate,
    ])
    return (
        <article className="space-y-2 rounded-lg border p-4">
            <p className="break-all font-medium">{reference.operation_id}</p>
            <p role="status">
                {t(
                    reference.rejected
                        ? 'dsh.rejected'
                        : `dsh.${operation?.status || 'PROCESSING'}`,
                )}
                {unavailable && ` · ${t('dsh.unavailable')}`}
            </p>
            {paused && <p>{t('dsh.pollPaused')}</p>}
            {!terminal && (
                <Button
                    variant="outline"
                    onClick={() => setRevision((old) => old + 1)}
                >
                    {t('dsh.checkOperation')}
                </Button>
            )}
            {!terminal && reference.retry && (unavailable || paused) && (
                <Button
                    variant="outline"
                    disabled={retrying}
                    onClick={async () => {
                        setRetrying(true)
                        try {
                            await reference.retry?.()
                        } finally {
                            setRetrying(false)
                            setRevision((old) => old + 1)
                        }
                    }}
                >
                    {t('dsh.retrySame')}
                </Button>
            )}
            {operation && (
                <>
                    <p>
                        {t('dsh.actor')}: {operation.actor_user_id ?? '—'} ·{' '}
                        {t('dsh.user')}: {operation.user_id} · {t('dsh.tenant')}
                        : {operation.tenant_id}
                    </p>
                    <p>
                        {t('dsh.action')}: {operation.action}
                    </p>
                    <p>
                        {t('dsh.expectedVersion')}:{' '}
                        {operation.expected_policy_version ??
                            operation.expected_grant_version ??
                            '—'}
                    </p>
                    <p>
                        {t('dsh.committed')}: {dshTime(operation.committed_at)}{' '}
                        · {t('dsh.effective')}:{' '}
                        {dshTime(operation.effective_at)}
                    </p>
                    {typeof operation.result_payload?.phase === 'string' && (
                        <p>
                            {t('dsh.phase')}: {t(`dsh.phases.${operation.result_payload.phase}`, { defaultValue: operation.result_payload.phase })}
                        </p>
                    )}
                    {operation.result_code && <p>{operation.result_code}</p>}
                    <details>
                        <summary className="cursor-pointer">
                            {t('dsh.audit')}
                        </summary>
                        <div className="grid gap-4 md:grid-cols-2">
                            <div>
                                <h4>{t('dsh.before')}</h4>
                                <pre className="overflow-x-auto whitespace-pre-wrap break-all text-xs">
                                    {JSON.stringify(
                                        operation.before_values,
                                        null,
                                        2,
                                    )}
                                </pre>
                            </div>
                            <div>
                                <h4>{t('dsh.after')}</h4>
                                <pre className="overflow-x-auto whitespace-pre-wrap break-all text-xs">
                                    {JSON.stringify(
                                        operation.after_values,
                                        null,
                                        2,
                                    )}
                                </pre>
                            </div>
                        </div>
                    </details>
                </>
            )}
        </article>
    )
}
