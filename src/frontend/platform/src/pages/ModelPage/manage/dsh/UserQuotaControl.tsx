import { Button } from '@/components/bs-ui/button'
import { useTranslation } from 'react-i18next'
import type { DshModelUserPermission } from '@/types/dsh'
import type { PolicyDraft } from './SubjectPolicyControls'
import { QuotaInput } from './QuotaInput'

interface Props {
    item: DshModelUserPermission
    draft: PolicyDraft
    disabled: boolean
    onChange: (patch: Partial<PolicyDraft>) => void
}
export function UserQuotaControl({ item, draft, disabled, onChange }: Props) {
    const { t } = useTranslation()
    return (
        <div className="flex min-w-0 items-center gap-3">
            {draft.enabled ? (
                <>
                    <div className="w-32 shrink-0">
                        <QuotaInput label={item.user_name + ' · ' + t('dsh.configuredQuotaWan')} value={draft.limit} disabled={disabled} onChange={(limit) => onChange({ limit })} />
                    </div>
                    <Button variant="link" size="sm" className="h-8 px-0 text-xs" disabled={disabled} onClick={() => onChange({ enabled: false, limit: '0' })}>
                        {t('dsh.restoreInheritance')}
                    </Button>
                </>
            ) : (
                <>
                    <span className="text-sm text-muted-foreground">{t('dsh.followDepartment')}</span>
                    <Button variant="link" size="sm" className="h-8 px-0 text-xs" disabled={disabled} onClick={() => onChange({ enabled: true, limit: String(item.monthly_token_limit) })}>
                        {t('dsh.setIndividualQuota')}
                    </Button>
                </>
            )}
        </div>
    )
}
