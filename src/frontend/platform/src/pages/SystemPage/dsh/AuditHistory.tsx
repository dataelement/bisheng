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
import { getDshAuditRecords } from '@/controllers/API/dshAudit'
import {
    auditActions,
    auditStatuses,
    type DshAuditPage,
    type DshAuditQuery,
    type DshAuditRecord,
    type DshAuditValues,
} from '@/types/dshAudit'
import { Fragment, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DshChoice, DshPager } from './common'

interface AuditHistoryProps {
    revision?: number
}

export function AuditHistory({ revision = 0 }: AuditHistoryProps) {
    const { t, i18n } = useTranslation()
    const [query, setQuery] = useState<DshAuditQuery>({ limit: 20 })
    const [cursors, setCursors] = useState<(string | undefined)[]>([])
    const [page, setPage] = useState<DshAuditPage | null>(null)
    const [failed, setFailed] = useState(false)
    const [loading, setLoading] = useState(true)
    const [refresh, setRefresh] = useState(0)
    const [expanded, setExpanded] = useState<string | null>(null)
    useEffect(() => {
        const abort = new AbortController()
        setLoading(true)
        setFailed(false)
        setPage(null)
        setExpanded(null)
        getDshAuditRecords(query, abort.signal)
            .then((result) => {
                if (abort.signal.aborted) return
                setPage(result)
                setLoading(false)
            })
            .catch(() => {
                if (abort.signal.aborted) return
                setFailed(true)
                setLoading(false)
            })
        return () => abort.abort()
    }, [query, refresh, revision])

    const handleFilter = (changes: Partial<DshAuditQuery>) => {
        setCursors([])
        setQuery((old) => ({ ...old, ...changes, cursor: undefined }))
    }
    const time = (value: string) =>
        new Date(value).toLocaleString(i18n.language || 'zh-CN', {
            timeZone: 'Asia/Shanghai',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        })

    return (
        <section className="space-y-4" aria-label={t('dsh.auditHistory.title')}>
            <div className="flex flex-wrap items-center justify-end gap-2">
                <DshChoice
                    label={t('dsh.action')}
                    value={query.action || 'ALL'}
                    options={[
                        {
                            value: 'ALL',
                            label: t('dsh.auditHistory.allActions'),
                        },
                        ...auditActions.map((value) => ({
                            value,
                            label: t(`dsh.auditHistory.actions.${value}`),
                        })),
                    ]}
                    onChange={(value) =>
                        handleFilter({
                            action:
                                value === 'ALL'
                                    ? undefined
                                    : (value as DshAuditQuery['action']),
                        })
                    }
                />
                <DshChoice
                    label={t('dsh.auditHistory.result')}
                    value={query.status || 'ALL'}
                    options={[
                        {
                            value: 'ALL',
                            label: t('dsh.auditHistory.allStatuses'),
                        },
                        ...auditStatuses.map((value) => ({
                            value,
                            label: t(`dsh.${value}`),
                        })),
                    ]}
                    onChange={(value) =>
                        handleFilter({
                            status:
                                value === 'ALL'
                                    ? undefined
                                    : (value as DshAuditQuery['status']),
                        })
                    }
                />
                <Button
                    variant="outline"
                    disabled={loading}
                    onClick={() => {
                        handleFilter({})
                        setRefresh((old) => old + 1)
                    }}
                >
                    {t('dsh.refresh')}
                </Button>
            </div>
            {failed ? (
                <p role="alert">{t('dsh.auditHistory.loadError')}</p>
            ) : loading ? (
                <p role="status">{t('dsh.loading')}</p>
            ) : (
                <div className="overflow-x-auto rounded-lg border">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                {[
                                    'time',
                                    'action',
                                    'actor',
                                    'target',
                                    'model',
                                    'result',
                                    'details',
                                ].map((key) => (
                                    <TableHead
                                        key={key}
                                        className={key === 'result' ? 'text-center' : undefined}
                                    >
                                        {t(`dsh.auditHistory.${key}`)}
                                    </TableHead>
                                ))}
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {!page?.data.length && (
                                <TableRow>
                                    <TableCell
                                        colSpan={7}
                                        className="text-center"
                                    >
                                        {t('dsh.auditHistory.empty')}
                                    </TableCell>
                                </TableRow>
                            )}
                            {page?.data.map((row) => (
                                <Fragment key={row.id}>
                                    <TableRow>
                                        <TableCell className="whitespace-nowrap">
                                            {time(row.created_at)}
                                        </TableCell>
                                        <TableCell>
                                            {t(
                                                `dsh.auditHistory.actions.${row.action}`,
                                            )}
                                        </TableCell>
                                        <TableCell>
                                            {row.actor_name ||
                                                (row.actor_id === null
                                                    ? t(
                                                          'dsh.auditHistory.system',
                                                      )
                                                    : `#${row.actor_id}`)}
                                        </TableCell>
                                        <TableCell>
                                            <p>
                                                {row.target_name ||
                                                    `#${row.target_id}`}
                                            </p>
                                            <p className="text-xs text-muted-foreground">
                                                {t(
                                                    `dsh.auditHistory.types.${row.target_type}`,
                                                )}{' '}
                                                · #{row.target_id}
                                            </p>
                                        </TableCell>
                                        <TableCell>
                                            {row.model_name ||
                                                (row.model_id === null
                                                    ? '—'
                                                    : `#${row.model_id}`)}
                                        </TableCell>
                                        <TableCell className="text-center">
                                            <Badge
                                                variant={
                                                    row.status === 'FAILED'
                                                        ? 'destructive'
                                                        : 'secondary'
                                                }
                                                className={
                                                    row.status === 'SUCCEEDED'
                                                        ? 'text-green-600'
                                                        : undefined
                                                }
                                            >
                                                {t(`dsh.${row.status}`)}
                                            </Badge>
                                        </TableCell>
                                        <TableCell>
                                            <Button
                                                variant="link"
                                                aria-expanded={
                                                    expanded === row.id
                                                }
                                                onClick={() =>
                                                    setExpanded(
                                                        expanded === row.id
                                                            ? null
                                                            : row.id,
                                                    )
                                                }
                                            >
                                                {t(
                                                    expanded === row.id
                                                        ? 'dsh.auditHistory.collapse'
                                                        : 'dsh.auditHistory.details',
                                                )}
                                            </Button>
                                        </TableCell>
                                    </TableRow>
                                    {expanded === row.id && (
                                        <TableRow>
                                            <TableCell colSpan={7}>
                                                <AuditDetails record={row} />
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </Fragment>
                            ))}
                        </TableBody>
                    </Table>
                </div>
            )}
            <DshPager
                className="justify-end"
                hideUnavailable
                previous={cursors.length > 0}
                next={!!page?.has_more}
                loading={loading}
                onPrevious={() => {
                    setQuery((old) => ({
                        ...old,
                        cursor: cursors[cursors.length - 1],
                    }))
                    setCursors((old) => old.slice(0, -1))
                }}
                onNext={() => {
                    if (!page?.next_cursor) return
                    setCursors((old) => [...old, query.cursor])
                    setQuery((old) => ({ ...old, cursor: page.next_cursor! }))
                }}
            />
        </section>
    )
}

interface AuditDetailsProps {
    record: DshAuditRecord
}
function AuditDetails({ record }: AuditDetailsProps) {
    const { t } = useTranslation()
    const fields = [
        ...new Set([
            ...Object.keys(record.before_values),
            ...Object.keys(record.after_values),
        ]),
    ]
    const format = (value: DshAuditValues[string] | undefined): string => {
        if (value === null || value === undefined) return '—'
        if (typeof value === 'boolean')
            return t(
                value
                    ? 'dsh.auditHistory.enabled'
                    : 'dsh.auditHistory.disabled',
            )
        if (typeof value === 'number') return value.toLocaleString()
        return [
            'ASSIGNED',
            'REVOKED',
            'PENDING',
            'PROCESSING',
            'SUCCEEDED',
            'FAILED',
        ].includes(value)
            ? t(`dsh.${value}`)
            : value
    }
    return (
        <div className="space-y-3 p-2">
            <p className="break-all text-xs text-muted-foreground">
                {t('dsh.auditHistory.recordId')}: {record.id}
            </p>
            {record.result_code && (
                <p>
                    {t('dsh.auditHistory.resultCode')}: {record.result_code}
                </p>
            )}
            {fields.length > 0 ? (
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>{t('dsh.auditHistory.field')}</TableHead>
                            <TableHead>{t('dsh.before')}</TableHead>
                            <TableHead>{t('dsh.after')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {fields.map((field) => (
                            <TableRow key={field}>
                                <TableCell>
                                    {t(`dsh.auditHistory.fields.${field}`, {
                                        defaultValue: field,
                                    })}
                                </TableCell>
                                <TableCell>
                                    {format(record.before_values[field])}
                                </TableCell>
                                <TableCell>
                                    {format(record.after_values[field])}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            ) : (
                <p className="text-muted-foreground">
                    {t('dsh.auditHistory.noSnapshot')}
                </p>
            )}
            {Object.keys(record.requested_values).length > 0 && (
                <div>
                    <p className="font-medium">
                        {t('dsh.auditHistory.requested')}
                    </p>
                    <dl>
                        {Object.entries(record.requested_values).map(
                            ([field, value]) => (
                                <div key={field} className="flex gap-3">
                                    <dt>
                                        {t(`dsh.auditHistory.fields.${field}`, {
                                            defaultValue: field,
                                        })}
                                    </dt>
                                    <dd>{format(value)}</dd>
                                </div>
                            ),
                        )}
                    </dl>
                </div>
            )}
        </div>
    )
}
