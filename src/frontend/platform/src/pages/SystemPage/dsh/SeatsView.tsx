import { Button } from '@/components/bs-ui/button'
import { Input } from '@/components/bs-ui/input'
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/bs-ui/table'
import {
    commandDshSeat,
    getDshSeats,
    isDshRequestRejected,
} from '@/controllers/API/dsh'
import type {
    DshOperation,
    DshOperationRef,
    DshPage,
    DshSeat,
    DshSeatQuery,
} from '@/types/dsh'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DshChoice, DshPager, dshTime } from './common'
import { SeatSessions } from './SeatSessions'

interface SeatsViewProps {
    onOperation: (operation: DshOperationRef, result?: DshOperation) => void
    operations: Record<string, DshOperation>
    revision: number
}
export function SeatsView({
    onOperation,
    operations,
    revision,
}: SeatsViewProps) {
    const { t } = useTranslation()
    const [keyword, setKeyword] = useState('')
    const [query, setQuery] = useState<DshSeatQuery>({ seat_state: 'ASSIGNED' })
    const [cursors, setCursors] = useState<string[]>([''])
    const [data, setData] = useState<DshPage<DshSeat> | null>(null)
    const [error, setError] = useState(false)
    const [seat, setSeat] = useState<DshSeat | null>(null)
    const [pending, setPending] = useState<Record<string, string>>({})
    const commandLocks = useRef(new Set<string>())
    useEffect(() => {
        for (const [seatId, operationId] of Object.entries(pending)) {
            if (
                ['SUCCEEDED', 'FAILED'].includes(
                    operations[operationId]?.status,
                )
            )
                commandLocks.current.delete(seatId)
        }
    }, [pending, operations])
    useEffect(() => {
        const normalizedKeyword = keyword.trim() || undefined
        if (normalizedKeyword === query.keyword) return
        const timer = window.setTimeout(() => {
            setQuery((old) => ({
                ...old,
                keyword: normalizedKeyword,
            }))
            setCursors([''])
        }, 300)
        return () => window.clearTimeout(timer)
    }, [keyword, query.keyword])
    useEffect(() => {
        const abort = new AbortController()
        setData(null)
        setError(false)
        setSeat(null)
        getDshSeats(
            { ...query, cursor: cursors.at(-1) || undefined, limit: 50 },
            abort.signal,
        )
            .then((result) => {
                if (!abort.signal.aborted) setData(result)
            })
            .catch(() => {
                if (!abort.signal.aborted) setError(true)
            })
        return () => abort.abort()
    }, [query, cursors, revision])
    function handleFilter(value: Partial<DshSeatQuery>) {
        setQuery((old) => ({ ...old, ...value }))
        setCursors([''])
    }
    function handleCommand(item: DshSeat) {
        const action = item.state === 'ASSIGNED' ? 'revoke' : 'reassign'
        bsConfirm({
            title: t(`dsh.${action}`),
            desc: t(`dsh.${action}Help`, {
                name: item.display_name || item.username || item.user_id,
            }),
            onOk: (next) => {
                if (commandLocks.current.has(item.seat_id)) {
                    next()
                    return
                }
                commandLocks.current.add(item.seat_id)
                const operationId = crypto.randomUUID()
                setPending((old) => ({ ...old, [item.seat_id]: operationId }))
                const ref: DshOperationRef = {
                    operation_id: operationId,
                    tenant_id: item.tenant_id,
                }
                ref.retry = async () => {
                    try {
                        onOperation(
                            ref,
                            await commandDshSeat(
                                item.user_id,
                                item.tenant_id,
                                action,
                                operationId,
                                item.grant_version,
                            ),
                        )
                    } catch (failure) {
                        if (isDshRequestRejected(failure)) {
                            onOperation({ ...ref, rejected: true })
                            commandLocks.current.delete(item.seat_id)
                            setPending((old) => {
                                const nextPending = { ...old }
                                delete nextPending[item.seat_id]
                                return nextPending
                            })
                        }
                    }
                }
                onOperation(ref)
                next()
                void ref.retry()
            },
        })
    }
    return (
        <section className="space-y-4">
            <div className="flex flex-wrap gap-2">
                <Input
                    className="w-56"
                    aria-label={t('dsh.searchUsers')}
                    placeholder={t('dsh.searchUsers')}
                    value={keyword}
                    onChange={(event) => setKeyword(event.target.value)}
                />
                <DshChoice
                    label={t('dsh.seatState')}
                    value={query.seat_state!}
                    options={['ASSIGNED', 'REVOKED'].map((value) => ({
                        value,
                        label: t(`dsh.${value}`),
                    }))}
                    onChange={(value) =>
                        handleFilter({
                            seat_state: value as DshSeatQuery['seat_state'],
                        })
                    }
                />
                <DshChoice
                    label={t('dsh.loginState')}
                    value={query.login_state || 'ALL'}
                    options={['ALL', 'HAS_SESSIONS', 'NO_SESSIONS'].map(
                        (value) => ({ value, label: t(`dsh.${value}`) }),
                    )}
                    onChange={(value) =>
                        handleFilter({
                            login_state:
                                value === 'ALL'
                                    ? undefined
                                    : (value as DshSeatQuery['login_state']),
                        })
                    }
                />
            </div>
            {!data ? (
                <p role="status">
                    {t(error ? 'dsh.unavailable' : 'dsh.loading')}
                </p>
            ) : (
                <div className="overflow-x-auto rounded-lg border">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                {[
                                    'user',
                                    'tenant',
                                    'seatState',
                                    'loginState',
                                    'lastLogin',
                                    'lastSeen',
                                    'actions',
                                ].map((key) => (
                                    <TableHead key={key}>
                                        {t(`dsh.${key}`)}
                                    </TableHead>
                                ))}
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.items.map((item) => {
                                const operation =
                                    operations[pending[item.seat_id]]
                                const busy =
                                    !!pending[item.seat_id] &&
                                    (!operation ||
                                        !['SUCCEEDED', 'FAILED'].includes(
                                            operation.status,
                                        ))
                                return (
                                    <TableRow key={item.seat_id}>
                                        <TableCell>
                                            <div>
                                                {item.display_name ||
                                                    item.username ||
                                                    item.user_id}
                                            </div>
                                            <span className="text-xs text-muted-foreground">
                                                {item.user_id}
                                            </span>
                                        </TableCell>
                                        <TableCell>{item.tenant_id}</TableCell>
                                        <TableCell>
                                            {t(`dsh.${item.state}`)}
                                        </TableCell>
                                        <TableCell>
                                            {t(`dsh.${item.login_state}`)}{' '}
                                            {item.login_state === 'UNAVAILABLE'
                                                ? ''
                                                : (item.active_session_count ??
                                                  '')}
                                        </TableCell>
                                        <TableCell>
                                            {dshTime(item.last_login_at)}
                                        </TableCell>
                                        <TableCell>
                                            {dshTime(item.last_seen_at)}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex gap-2">
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() =>
                                                        setSeat(item)
                                                    }
                                                >
                                                    {t('dsh.sessions')}
                                                </Button>
                                                <Button
                                                    size="sm"
                                                    variant={
                                                        item.state ===
                                                        'ASSIGNED'
                                                            ? 'destructive'
                                                            : 'outline'
                                                    }
                                                    disabled={busy}
                                                    onClick={() =>
                                                        handleCommand(item)
                                                    }
                                                >
                                                    {t(
                                                        busy
                                                            ? 'dsh.PROCESSING'
                                                            : item.state ===
                                                                'ASSIGNED'
                                                              ? 'dsh.revoke'
                                                              : 'dsh.reassign',
                                                    )}
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                )
                            })}
                        </TableBody>
                    </Table>
                    {!data.items.length && (
                        <p className="p-4">{t('dsh.empty')}</p>
                    )}
                </div>
            )}
            <DshPager
                previous={cursors.length > 1}
                next={!!data?.has_more}
                loading={!data && !error}
                onPrevious={() => setCursors((old) => old.slice(0, -1))}
                onNext={() =>
                    data?.next_cursor &&
                    setCursors((old) => [...old, data.next_cursor!])
                }
            />
            {seat && <SeatSessions key={seat.seat_id} seat={seat} />}
        </section>
    )
}
