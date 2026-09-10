import { Button } from '@/components/bs-ui/button'
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from '@/components/bs-ui/tabs'
import { getDshLicense } from '@/controllers/API/dsh'
import type { DshLicense, DshOperation, DshOperationRef } from '@/types/dsh'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { OperationStatus } from './OperationStatus'
import { PolicyView } from './PolicyView'
import { SeatsView } from './SeatsView'
import { dshTime } from './common'

export function DshManagement() {
    const { t } = useTranslation()
    const [license, setLicense] = useState<DshLicense | null>(null)
    const [error, setError] = useState(false)
    const [references, setReferences] = useState<DshOperationRef[]>([])
    const [operations, setOperations] = useState<Record<string, DshOperation>>(
        {},
    )
    const [revision, setRevision] = useState(0)
    const refreshedOperations = useRef(new Set<string>())
    useEffect(() => {
        const abort = new AbortController()
        setError(false)
        setLicense(null)
        getDshLicense(abort.signal)
            .then((value) => {
                if (!abort.signal.aborted) setLicense(value)
            })
            .catch(() => {
                if (!abort.signal.aborted) setError(true)
            })
        return () => abort.abort()
    }, [revision])
    const handleOperation = useCallback(
        (ref: DshOperationRef, result?: DshOperation) => {
            setReferences((old) =>
                old.some((item) => item.operation_id === ref.operation_id)
                    ? old.map((item) =>
                          item.operation_id === ref.operation_id
                              ? { ...item, ...ref }
                              : item,
                      )
                    : [ref, ...old],
            )
            if (result) {
                setOperations((old) => ({ ...old, [ref.operation_id]: result }))
                if (
                    result.status === 'SUCCEEDED' &&
                    ['REVOKE', 'REASSIGN'].includes(result.action) &&
                    !refreshedOperations.current.has(ref.operation_id)
                ) {
                    refreshedOperations.current.add(ref.operation_id)
                    setRevision((old) => old + 1)
                }
            }
        },
        [],
    )
    return (
        <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
            <div className="flex items-center justify-between gap-4">
                <h2 className="text-lg font-semibold">{t('dsh.title')}</h2>
                <Button
                    variant="outline"
                    onClick={() => setRevision((old) => old + 1)}
                >
                    {t('dsh.refresh')}
                </Button>
            </div>
            <section className="space-y-2 rounded-lg border p-4">
                <h3 className="font-semibold">{t('dsh.license')}</h3>
                {!license ? (
                    <p role="status">
                        {t(error ? 'dsh.unavailable' : 'dsh.loading')}
                    </p>
                ) : (
                    <>
                        <p>
                            {license.status} ·{' '}
                            {t('dsh.seatSummary', {
                                assigned: license.assigned,
                                limit: license.seat_limit,
                                available: license.available,
                            })}
                        </p>
                        <p className="text-sm text-muted-foreground">
                            {t('dsh.asOf')}: {dshTime(license.as_of)} ·{' '}
                            {t('dsh.expires')}: {dshTime(license.expires_at)}
                        </p>
                    </>
                )}
            </section>
            <Tabs defaultValue="seats">
                <TabsList>
                    <TabsTrigger value="seats">{t('dsh.seats')}</TabsTrigger>
                    <TabsTrigger value="policy">{t('dsh.userUsage')}</TabsTrigger>
                    <TabsTrigger value="operations">
                        {t('dsh.operations')} ({references.length})
                    </TabsTrigger>
                </TabsList>
                <TabsContent
                    forceMount
                    value="seats"
                    className="data-[state=inactive]:hidden"
                >
                    <SeatsView
                        onOperation={handleOperation}
                        operations={operations}
                        revision={revision}
                    />
                </TabsContent>
                <TabsContent
                    forceMount
                    value="policy"
                    className="data-[state=inactive]:hidden"
                >
                    <PolicyView />
                </TabsContent>
                <TabsContent value="operations">
                    <p className="mb-4 text-sm text-muted-foreground">
                        {t('dsh.operationHelp')}
                    </p>
                    {!references.length && <p>{t('dsh.empty')}</p>}
                </TabsContent>
            </Tabs>
            <div className="space-y-3">
                {references.map((ref) => (
                    <OperationStatus
                        key={ref.operation_id}
                        reference={ref}
                        operation={operations[ref.operation_id]}
                        onUpdate={handleOperation}
                    />
                ))}
            </div>
        </div>
    )
}
