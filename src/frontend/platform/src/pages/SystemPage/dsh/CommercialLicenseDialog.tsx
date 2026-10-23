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
import { copyText } from '@/utils'
import { Textarea } from '@/components/bs-ui/input'
import { licenseStatusKey } from './licensePresentation'
import type { DshLicense } from '@/types/dsh'
import { useTranslation } from 'react-i18next'

const COMMERCIAL_LICENSE_EMAIL = 'bisheng@dataelem.com'

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
    const licenseStatus = license
        ? t(`dsh.licenseStatus.${licenseStatusKey(license)}`, {
              defaultValue: license.status,
          })
        : t('dsh.notConfigured')

    const application = t('dsh.commercialLicenseApplication', {
        organization: tenantName || t('dsh.applicationCompanyPlaceholder'),
        deployment: deploymentAddress,
        interpolation: { escapeValue: false },
    })
    const mailto = `mailto:${COMMERCIAL_LICENSE_EMAIL}?subject=${encodeURIComponent(t('dsh.commercialLicenseSubject'))}&body=${encodeURIComponent(application)}`

    async function copyApplicationInfo() {
        try {
            await copyText(application)
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
                        {' '}<a className="text-primary underline" href={mailto}>{COMMERCIAL_LICENSE_EMAIL}</a>
                    </DialogDescription>
                </DialogHeader>
                <p className="text-sm">{licenseStatus}</p>
                <Textarea
                    aria-label={t('dsh.commercialLicenseSubject')}
                    readOnly
                    rows={9}
                    value={application}
                />
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
