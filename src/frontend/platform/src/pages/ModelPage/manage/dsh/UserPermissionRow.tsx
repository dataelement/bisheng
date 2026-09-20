import { Badge } from '@/components/bs-ui/badge'
import { Input } from '@/components/bs-ui/input'
import { TableCell, TableRow } from '@/components/bs-ui/table'
import type { DshModelUserPermission } from '@/types/dsh'
import { useTranslation } from 'react-i18next'
import type { PolicyDraft } from './SubjectPolicyControls'
import { validUserDraft } from './useUserPolicyDrafts'

interface UserPermissionRowProps {
    item: DshModelUserPermission
    draft: PolicyDraft
    disabled: boolean
    pending: boolean
    onDraftChange: (patch: Partial<PolicyDraft>) => void
}

export function UserPermissionRow({ item, draft, disabled, pending, onDraftChange }: UserPermissionRowProps) {
    const { t } = useTranslation()
    const valid = validUserDraft(draft)
    return (
        <TableRow>
            <TableCell className="font-medium">
                <div className="break-words">{item.user_name}</div>
                <div className="mt-1 text-xs font-normal text-muted-foreground">ID: {item.user_id}</div>
            </TableCell>
            <TableCell className="whitespace-nowrap">
                <Badge
                    variant={item.authorized ? 'secondary' : 'outline'}
                    className={`whitespace-nowrap ${item.authorized ? 'text-green-600' : ''}`}
                >
                    {t(item.authorized ? 'dsh.authorized' : 'dsh.unauthorized')}
                </Badge>
            </TableCell>
            <TableCell>
                <Input
                    boxClassName="w-48 max-w-full"
                    className="h-8 tabular-nums"
                    aria-label={t('dsh.userMonthlyLimit', { name: item.user_name })}
                    aria-invalid={!valid}
                    inputMode="numeric"
                    placeholder="0"
                    value={draft.limit}
                    disabled={disabled || pending}
                    onChange={(event) => onDraftChange({ limit: event.target.value })}
                />
                {!valid && (
                    <p role="alert" className="mt-1 text-xs text-destructive">
                        {t('dsh.quotaInvalid')}
                    </p>
                )}
            </TableCell>
        </TableRow>
    )
}
