import { Button, Textarea, toast } from '@bisheng/ui';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";


import type { DshLicense } from "@/types/dsh";
import { copyText } from "@/utils";
import { useTranslation } from "react-i18next";
import { licenseStatusKey } from "./licensePresentation";

const COMMERCIAL_LICENSE_EMAIL = "bisheng@dataelem.com";

interface CommercialLicenseDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  license: DshLicense | null;
  tenantName: string;
}

export function CommercialLicenseDialog({ open, onOpenChange, license, tenantName }: CommercialLicenseDialogProps) {
  const { t } = useTranslation();

  const deploymentAddress = window.location.origin;
  const licenseStatus = license
    ? t(`dsh.licenseStatus.${licenseStatusKey(license)}`, {
        defaultValue: license.status,
      })
    : t("dsh.notConfigured");

  const application = t("dsh.commercialLicenseApplication", {
    organization: tenantName || t("dsh.applicationCompanyPlaceholder"),
    deployment: deploymentAddress,
    interpolation: { escapeValue: false },
  });
  const mailto = `mailto:${COMMERCIAL_LICENSE_EMAIL}?subject=${encodeURIComponent(t("dsh.commercialLicenseSubject"))}&body=${encodeURIComponent(application)}`;

  async function copyApplicationInfo() {
    try {
      await copyText(application);
      toast.show({ type: "success", message: String(t("dsh.applicationInfoCopied") ?? '') });
    } catch {
      toast.show({ type: "error", message: String(t("dsh.copyFailed") ?? '') });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("dsh.getCommercialLicense")}</DialogTitle>
          <DialogDescription>
            {t("dsh.commercialLicenseContact")}{" "}
            <a className="text-primary underline" href={mailto}>
              {COMMERCIAL_LICENSE_EMAIL}
            </a>
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">{licenseStatus}</p>
        <Textarea aria-label={t("dsh.commercialLicenseSubject")} readOnly rows={9} value={application} />
        <p className="text-sm text-muted-foreground">{t("dsh.commercialLicenseActivation")}</p>
        <DialogFooter>
          <Button variant="outlined" onClick={() => onOpenChange(false)} color="default">
            {t("dsh.close")}
          </Button>
          <Button onClick={copyApplicationInfo}>{t("dsh.copyApplicationInfo")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
