import { Button } from '@/components/bs-ui/button'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/bs-ui/dialog'
import { useToast } from '@/components/bs-ui/toast/use-toast'
import type { DshLicense } from '@/types/dsh'
import { useTranslation } from 'react-i18next'

export function CommercialLicenseDialog({
    open,
    onOpenChange,
    license,
    tenantName,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    license: DshLicense | null
    tenantName: string
}) {
    const { t } = useTranslation()
    const { message } = useToast()
    const deploymentAddress = window.location.origin
    const normalizedStatus = license?.status?.toLocaleLowerCase() || 'unknown'
    const licenseStatus = license
        ? t(`dsh.licenseStatus.${normalizedStatus === 'active' && license.source === 'builtin' ? 'free' : normalizedStatus}`, {
              defaultValue: license.status,
          })
        : t('dsh.notConfigured')

    async function copyApplicationInfo() {
        const lines = [
            `${t('dsh.organization')}: ${tenantName || t('dsh.notConfigured')}`,
            `${t('dsh.deploymentAddress')}: ${deploymentAddress}`,
            `${t('dsh.currentLicenseStatus')}: ${licenseStatus}`,
            `${t('dsh.currentSeatLimit')}: ${license?.seat_limit ?? 0}`,
        ]
        if (license?.license_id) {
            lines.push(`${t('dsh.licenseId')}: ${license.license_id}`)
        }
        try {
            await navigator.clipboard.writeText(lines.join('\n'))
            message({
                variant: 'success',
                description: t('dsh.applicationInfoCopied'),
            })
        } catch {
            message({ variant: 'error', description: t('dsh.copyFailed') })
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{t('dsh.getCommercialLicense')}</DialogTitle>
                    <DialogDescription>
                        {t('dsh.commercialLicenseContact')}
                    </DialogDescription>
                </DialogHeader>
                <div className="space-y-3 rounded-lg border bg-muted/30 p-4 text-sm">
                    <InfoRow label={t('dsh.organization')} value={tenantName || '—'} />
                    <InfoRow
                        label={t('dsh.deploymentAddress')}
                        value={deploymentAddress}
                    />
                    <InfoRow
                        label={t('dsh.currentLicenseStatus')}
                        value={licenseStatus}
                    />
                    <InfoRow
                        label={t('dsh.currentSeatLimit')}
                        value={String(license?.seat_limit ?? 0)}
                    />
                </div>
                <p className="text-sm text-muted-foreground">
                    {t('dsh.commercialLicenseActivation')}
                </p>
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {t('dsh.close')}
                    </Button>
                    <Button
                        className="active:scale-[0.97]"
                        onClick={copyApplicationInfo}
                    >
                        {t('dsh.copyApplicationInfo')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

function InfoRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
            <span className="text-muted-foreground">{label}</span>
            <span className="break-all font-medium">{value}</span>
        </div>
    )
}
