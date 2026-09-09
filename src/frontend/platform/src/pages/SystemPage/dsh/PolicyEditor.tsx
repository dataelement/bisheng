import { Button } from '@/components/bs-ui/button'
import { Checkbox } from '@/components/bs-ui/checkBox'
import { Input } from '@/components/bs-ui/input'
import { isDshRequestRejected, saveDshPolicy } from '@/controllers/API/dsh'
import type { DshOperation, DshOperationRef, DshPolicy } from '@/types/dsh'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

interface PolicyEditorProps {
    userId: string
    tenantId: string
    policy: DshPolicy
    onOperation: (ref: DshOperationRef, result?: DshOperation) => void
    operations: Record<string, DshOperation>
    onReload: () => void
}
export function PolicyEditor({
    userId,
    tenantId,
    policy,
    onOperation,
    operations,
    onReload,
}: PolicyEditorProps) {
    const { t } = useTranslation()
    const [models, setModels] = useState(() =>
        policy.models.map((model) => ({
            model_id: model.model_id,
            limit: String(model.monthly_token_limit),
        })),
    )
    const [operationId, setOperationId] = useState<string | null>(
        policy.pending_operation_id ?? null,
    )
    useEffect(() => {
        if (policy.pending_operation_id)
            onOperation({
                operation_id: policy.pending_operation_id,
                tenant_id: tenantId,
            })
    }, [policy.pending_operation_id, tenantId, onOperation])
    const submitting = useRef(false)
    const [error, setError] = useState(false)
    const [rejected, setRejected] = useState(false)
    const result = operationId ? operations[operationId] : undefined
    const pending =
        !!operationId &&
        (!result || !['SUCCEEDED', 'FAILED'].includes(result.status))
    const stale =
        rejected ||
        result?.status === 'SUCCEEDED' ||
        result?.status === 'FAILED'
    const valid = models.every(
        ({ limit }) =>
            /^\d+$/.test(limit) && Number.isSafeInteger(Number(limit)),
    )
    async function handleSave() {
        if (
            !valid ||
            submitting.current ||
            pending ||
            stale ||
            modelsUnavailable
        )
            return
        submitting.current = true
        setError(false)
        const id = crypto.randomUUID()
        setOperationId(id)
        const body = {
            operation_id: id,
            expected_version: policy.version,
            models: models.map(({ model_id, limit }) => ({
                model_id,
                monthly_token_limit: Number(limit),
            })),
        }
        const ref: DshOperationRef = { operation_id: id, tenant_id: tenantId }
        ref.retry = async () => {
            try {
                onOperation(ref, await saveDshPolicy(userId, tenantId, body))
            } catch (failure) {
                setError(true)
                if (isDshRequestRejected(failure)) {
                    setRejected(true)
                    onOperation({ ...ref, rejected: true })
                    setOperationId(null)
                }
            }
        }
        onOperation(ref)
        try {
            await ref.retry()
        } finally {
            submitting.current = false
        }
    }
    const modelsUnavailable = policy.available_models_source !== 'live'
    const available = policy.available_models
    const availableIds = new Set(available.map((model) => model.id))
    return (
        <section className="space-y-4 rounded-lg border p-4">
            <h3 className="font-semibold">{t('dsh.editPolicy')}</h3>
            <p>
                {t('dsh.version', { version: policy.version })} ·{' '}
                {t(`dsh.${policy.quota_sync_state}`)}
            </p>
            <fieldset
                disabled={pending || !!stale || modelsUnavailable}
                className="space-y-3"
            >
                <legend className="mb-2 text-sm font-medium">
                    {t('dsh.models')}
                </legend>
                {available.map((model) => {
                    const config = models.find(
                        (item) => item.model_id === model.id,
                    )
                    return (
                        <div key={model.id} className="space-y-2">
                            <label className="flex items-center gap-2 text-sm">
                                <Checkbox
                                    checked={!!config}
                                    onCheckedChange={(checked) =>
                                        setModels((old) =>
                                            checked === true
                                                ? [
                                                      ...old,
                                                      {
                                                          model_id: model.id,
                                                          limit: '0',
                                                      },
                                                  ]
                                                : old.filter(
                                                      (item) =>
                                                          item.model_id !==
                                                          model.id,
                                                  ),
                                        )
                                    }
                                />
                                {model.name}{' '}
                                {model.is_root_shared && (
                                    <span className="text-muted-foreground">
                                        {t('dsh.shared')}
                                    </span>
                                )}
                            </label>
                            {config && (
                                <label className="block space-y-2">
                                    <span>
                                        {t('dsh.monthlyLimit', {
                                            model: model.name,
                                        })}
                                    </span>
                                    <Input
                                        inputMode="numeric"
                                        value={config.limit}
                                        onChange={(event) => {
                                            const limit = event.target.value
                                            setModels((old) =>
                                                old.map((item) =>
                                                    item.model_id === model.id
                                                        ? { ...item, limit }
                                                        : item,
                                                ),
                                            )
                                        }}
                                    />
                                </label>
                            )}
                        </div>
                    )
                })}
                {models
                    .filter((model) => !availableIds.has(model.model_id))
                    .map(({ model_id }) => (
                        <label
                            key={model_id}
                            className="flex items-center gap-2 text-sm"
                        >
                            <Checkbox
                                checked
                                onCheckedChange={() =>
                                    setModels((old) =>
                                        old.filter(
                                            (model) =>
                                                model.model_id !== model_id,
                                        ),
                                    )
                                }
                            />
                            {t('dsh.unavailableModel', { id: model_id })}
                        </label>
                    ))}
                {modelsUnavailable ? (
                    <p role="status">{t('dsh.modelsUnavailable')}</p>
                ) : (
                    !available.length && <p>{t('dsh.emptyModels')}</p>
                )}
            </fieldset>
            <p className="text-sm text-muted-foreground">
                {t('dsh.independentQuota')}
            </p>
            {!models.length && (
                <p role="note" className="text-sm text-muted-foreground">
                    {t('dsh.blockedPolicy')}
                </p>
            )}
            {models.some(
                ({ limit }) => limit !== '' && Number(limit) === 0,
            ) && (
                <p role="note" className="text-sm text-muted-foreground">
                    {t('dsh.zeroModelQuota')}
                </p>
            )}
            {error && (
                <p role="alert">
                    {t(rejected ? 'dsh.rejected' : 'dsh.saveUncertain')}
                </p>
            )}
            {pending && <p role="status">{t('dsh.PROCESSING')}</p>}
            {stale && <p role="status">{t('dsh.reloadPolicy')}</p>}
            <div className="flex gap-2">
                <Button
                    disabled={!valid || pending || !!stale || modelsUnavailable}
                    onClick={handleSave}
                >
                    {t('dsh.save')}
                </Button>
                <Button variant="outline" disabled={pending} onClick={onReload}>
                    {t('dsh.refresh')}
                </Button>
            </div>
        </section>
    )
}
