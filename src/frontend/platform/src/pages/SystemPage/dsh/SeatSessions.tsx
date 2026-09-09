import { getDshSessions } from '@/controllers/API/dsh'
import type { DshPage, DshSeat, DshSession } from '@/types/dsh'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/bs-ui/table'
import { DshPager, dshTime } from './common'

interface SeatSessionsProps {
    seat: DshSeat
}
export function SeatSessions({ seat }: SeatSessionsProps) {
    const { t } = useTranslation()
    const [cursors, setCursors] = useState<string[]>([''])
    const [data, setData] = useState<DshPage<DshSession> | null>(null)
    const [error, setError] = useState(false)
    useEffect(() => {
        const abort = new AbortController()
        setData(null)
        setError(false)
        getDshSessions(
            seat.user_id,
            seat.tenant_id,
            cursors.at(-1) || undefined,
            abort.signal,
        )
            .then((result) => {
                if (!abort.signal.aborted) setData(result)
            })
            .catch(() => {
                if (!abort.signal.aborted) setError(true)
            })
        return () => abort.abort()
    }, [seat.user_id, seat.tenant_id, cursors])
    return (
        <section className="space-y-3 rounded-lg border p-4">
            <h3 className="font-semibold">
                {t('dsh.sessions')} ·{' '}
                {seat.display_name || seat.username || seat.user_id}
            </h3>
            {!data ? (
                <p role="status">
                    {t(error ? 'dsh.unavailable' : 'dsh.loading')}
                </p>
            ) : (
                <>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                {[
                                    'device',
                                    'clientVersion',
                                    'state',
                                    'lastSeen',
                                    'expires',
                                ].map((key) => (
                                    <TableHead key={key}>
                                        {t(`dsh.${key}`)}
                                    </TableHead>
                                ))}
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {data.items.map((session) => (
                                <TableRow key={session.session_id}>
                                    <TableCell>
                                        {session.device_label || '—'}
                                    </TableCell>
                                    <TableCell>
                                        {session.client_version || '—'}
                                    </TableCell>
                                    <TableCell>{session.state}</TableCell>
                                    <TableCell>
                                        {dshTime(session.last_seen_at)}
                                    </TableCell>
                                    <TableCell>
                                        {dshTime(session.expires_at)}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                    {!data.items.length && <p>{t('dsh.empty')}</p>}
                </>
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
        </section>
    )
}
