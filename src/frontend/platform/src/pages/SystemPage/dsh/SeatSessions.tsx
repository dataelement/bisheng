import { getDshSessions } from '@/controllers/API/dsh'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/bs-ui/dialog'
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
    onClose: () => void
}
export function SeatSessions({ seat, onClose }: SeatSessionsProps) {
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
        <Dialog
            open
            onOpenChange={(open) => {
                if (!open) onClose()
            }}
        >
            <DialogContent
                className="max-h-[85vh] overflow-y-auto sm:max-w-3xl"
                aria-describedby={undefined}
            >
                <DialogHeader>
                    <DialogTitle>
                        {t('dsh.sessions')} ·{' '}
                        {seat.display_name || seat.username || seat.user_id}
                    </DialogTitle>
                </DialogHeader>
                {!data ? (
                    <p role="status">
                        {t(error ? 'dsh.unavailable' : 'dsh.loading')}
                    </p>
                ) : (
                    <div className="overflow-x-auto">
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
            </DialogContent>
        </Dialog>
    )
}
