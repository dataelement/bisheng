import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/bs-ui/dialog'
import { Input } from '@/components/bs-ui/input'
import {
    Table,
    TableBody,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/bs-ui/table'
import { getDshModelUsers } from '@/controllers/API/dsh'
import { DshPager } from '@/pages/SystemPage/dsh/common'
import { OperationStatus } from '@/pages/SystemPage/dsh/OperationStatus'
import type {
    DshModelAccessPage,
    DshOperation,
    DshOperationRef,
} from '@/types/dsh'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ModelAccessRow } from './ModelAccessRow'

export type DshAccessModel = { id: number; name: string }
type UserOperation = DshOperationRef & { user_id: number; model_id?: number }
interface ModelAccessDialogProps {
    model: DshAccessModel | null
    onClose: () => void
}
export function ModelAccessDialog({ model, onClose }: ModelAccessDialogProps) {
    const { t } = useTranslation()
    const [references, setReferences] = useState<UserOperation[]>([])
    const [operations, setOperations] = useState<Record<string, DshOperation>>(
        {},
    )
    const handleOperation = useCallback(
        (userId: number, reference: DshOperationRef, result?: DshOperation) => {
            setReferences((old) =>
                old.some((item) => item.operation_id === reference.operation_id)
                    ? old.map((item) =>
                          item.operation_id === reference.operation_id
                              ? { ...item, ...reference }
                              : item,
                      )
                    : [{ ...reference, user_id: userId }, ...old],
            )
            if (result)
                setOperations((old) => ({
                    ...old,
                    [reference.operation_id]: result,
                }))
        },
        [],
    )
    const handleUpdate = useCallback(
        (reference: DshOperationRef, result: DshOperation) => {
            handleOperation(result.user_id, reference, result)
        },
        [handleOperation],
    )
    return (
        <Dialog
            open={!!model}
            onOpenChange={(open) => {
                if (!open) onClose()
            }}
        >
            <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-4xl">
                <DialogHeader>
                    <DialogTitle>
                        {t('dsh.modelAccess')} · {model?.name}
                    </DialogTitle>
                    <DialogDescription>
                        {t('dsh.modelAccessHelp')}
                    </DialogDescription>
                </DialogHeader>
                {model && (
                    <ModelAccessUsers
                        key={model.id}
                        model={model}
                        operations={operations}
                        references={references}
                        onOperation={handleOperation}
                    />
                )}
                {references.length > 0 && (
                    <details>
                        <summary className="cursor-pointer">
                            {t('dsh.operations')} ({references.length})
                        </summary>
                        <div className="space-y-3 pt-3">
                            {references.map((reference) => (
                                <OperationStatus
                                    key={reference.operation_id}
                                    reference={reference}
                                    operation={
                                        operations[reference.operation_id]
                                    }
                                    onUpdate={handleUpdate}
                                />
                            ))}
                        </div>
                    </details>
                )}
            </DialogContent>
        </Dialog>
    )
}

interface ModelAccessUsersProps {
    model: DshAccessModel
    references: UserOperation[]
    operations: Record<string, DshOperation>
    onOperation: (
        userId: number,
        reference: DshOperationRef,
        result?: DshOperation,
    ) => void
}
function ModelAccessUsers({
    model,
    references,
    operations,
    onOperation,
}: ModelAccessUsersProps) {
    const { t } = useTranslation()
    const [keyword, setKeyword] = useState('')
    const [query, setQuery] = useState('')
    const [cursors, setCursors] = useState<string[]>([''])
    const [page, setPage] = useState<DshModelAccessPage | null>(null)
    const [error, setError] = useState(false)
    useEffect(() => {
        if (keyword.trim() === query) return
        const timer = window.setTimeout(() => {
            setQuery(keyword.trim())
            setCursors([''])
        }, 300)
        return () => window.clearTimeout(timer)
    }, [keyword, query])
    useEffect(() => {
        const abort = new AbortController()
        setPage(null)
        setError(false)
        getDshModelUsers(
            model.id,
            {
                cursor: cursors.at(-1) || undefined,
                keyword: query || undefined,
                limit: 20,
            },
            abort.signal,
        )
            .then((value) => {
                if (!abort.signal.aborted) setPage(value)
            })
            .catch(() => {
                if (!abort.signal.aborted) setError(true)
            })
        return () => abort.abort()
    }, [model.id, query, cursors])
    return (
        <section className="space-y-4">
            <Input
                className="max-w-sm"
                aria-label={t('dsh.searchUsers')}
                placeholder={t('dsh.searchUsers')}
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
            />
            <p className="text-sm text-muted-foreground">
                {t('dsh.preAuthorizeHelp')}
            </p>
            <p className="text-sm text-muted-foreground">
                {t('dsh.modelQuotaHelp')}
            </p>
            {!page ? (
                <p role="status">
                    {t(error ? 'dsh.unavailable' : 'dsh.loading')}
                </p>
            ) : (
                <div className="overflow-x-auto rounded-lg border">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('dsh.user')}</TableHead>
                                <TableHead>{t('dsh.allowed')}</TableHead>
                                <TableHead>{t('dsh.monthlyTokens')}</TableHead>
                                <TableHead>{t('dsh.actions')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {page.items.map((user) => (
                                <ModelAccessRow
                                    key={user.user_id}
                                    user={user}
                                    modelId={model.id}
                                    tenantId={page.tenant_id}
                                    operations={operations}
                                    rejectedOperationIds={references.filter((reference) => reference.rejected).map((reference) => reference.operation_id)}
                                    onOperation={onOperation}
                                    unresolved={references.find(
                                        (reference) =>
                                            reference.user_id ===
                                                user.user_id &&
                                            reference.model_id === model.id &&
                                            reference.tenant_id ===
                                                String(page.tenant_id) &&
                                            !reference.rejected &&
                                            !['SUCCEEDED', 'FAILED'].includes(
                                                operations[
                                                    reference.operation_id
                                                ]?.status,
                                            ),
                                    )}
                                />
                            ))}
                        </TableBody>
                    </Table>
                    {!page.items.length && (
                        <p className="p-4">{t('dsh.empty')}</p>
                    )}
                </div>
            )}
            <DshPager
                previous={cursors.length > 1}
                next={!!page?.has_more}
                loading={!page && !error}
                onPrevious={() => setCursors((old) => old.slice(0, -1))}
                onNext={() => {
                    if (page?.next_cursor)
                        setCursors((old) => [...old, page.next_cursor!])
                }}
            />
        </section>
    )
}
