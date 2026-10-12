import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm'
import { Button } from '@/components/bs-ui/button'
import { commandDshSeat, getDshSeats, isDshRequestRejected } from '@/controllers/API/dsh'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { createDshOperationId } from '@/util/dshOperationId'
import { createContext, useContext, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { resolveOperation, withinSaveDeadline } from './useUserPolicyDrafts'

export const SeatRestoreContext = createContext<{ tenantId: number; onRestored: () => void } | null>(null)

interface ReauthorizeSeatProps {
    userId: number
    name: string
    disabled: boolean
}

export function ReauthorizeSeat({ userId, name, disabled }: ReauthorizeSeatProps) {
    const { t } = useTranslation()
    const scope = useContext(SeatRestoreContext)
    const operation = useRef<string | null>(null)
    const locked = useRef(false)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState<string | null>(null)
    async function restore() {
        if (!scope || locked.current) return
        locked.current = true
        setBusy(true)
        setError(null)
        try {
            let result
            if (operation.current) {
                result = await resolveOperation(operation.current, scope.tenantId)
            } else {
                const page = await getDshSeats({ tenant_id: String(scope.tenantId), user_id: String(userId), seat_state: 'REVOKED', limit: 1 })
                const seat = page.items[0]
                if (!seat || seat.user_id !== String(userId) || seat.tenant_id !== String(scope.tenantId) || seat.state !== 'REVOKED') {
                    throw new Error('Seat changed; refresh before restoring')
                }
                operation.current = createDshOperationId()
                result = await withinSaveDeadline(commandDshSeat(seat.user_id, seat.tenant_id, 'reassign', operation.current, seat.grant_version))
                if (result.status !== 'SUCCEEDED' && result.status !== 'FAILED') {
                    result = await resolveOperation(operation.current, scope.tenantId)
                }
            }
            operation.current = null
            if (result.status === 'SUCCEEDED') scope.onRestored()
            else setError(getDshRequestErrorKey(result) ?? 'dsh.reauthorizeFailed')
        } catch (failure) {
            if (isDshRequestRejected(failure)) operation.current = null
            setError(getDshRequestErrorKey(failure) ?? 'dsh.reauthorizeFailed')
        } finally {
            locked.current = false
            setBusy(false)
        }
    }
    function handleRestore() {
        if (operation.current) { void restore(); return }
        bsConfirm({
            title: t('dsh.reauthorize'),
            desc: t('dsh.reauthorizeHelp', { name }),
            onOk: (next) => { next(); void restore() },
        })
    }
    return (
        <div className="space-y-1">
            <Button size="sm" variant="outline" className="h-6 py-0 leading-none" disabled={disabled || busy || !scope} onClick={handleRestore}>
                {t(busy ? 'dsh.reauthorizePending' : 'dsh.reauthorize')}
            </Button>
            {error && <p role="alert" className="text-xs text-red-600">{t(error)}</p>}
        </div>
    )
}
