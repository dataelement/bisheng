import { Alert, Button, Input, notification } from '@bisheng/ui';

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"

import { Label } from "@/components/bs-ui/label"
import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"

import { mountTenantApi } from "@/controllers/API/department"
import { grantTenantAdminApi } from "@/controllers/API/tenant"
import { showApiError } from "@/controllers/request"
import { useState } from "react"
import { useTranslation } from "react-i18next"

interface MountTenantDialogProps {
  deptId: number
  deptName: string
  onMounted: () => void
  onClose: () => void
}

export function MountTenantDialog({
  deptId,
  deptName,
  onMounted,
  onClose,
}: MountTenantDialogProps) {
  const { t } = useTranslation()
  const [tenantName, setTenantName] = useState(deptName)
  const [selectedAdmins, setSelectedAdmins] = useState<DepartmentUserOption[]>([])
  const [loading, setLoading] = useState(false)

  const canSubmit =
    tenantName.trim().length > 0 &&
    selectedAdmins.length > 0 &&
    !loading

  const handleSubmit = async () => {
        if ((String((tenantName) ?? '').length > 128)) return;

    if (!canSubmit) return
    setLoading(true)
    try {
      const mounted = await mountTenantApi(deptId, {
          tenant_name: tenantName.trim(),
        })
      if (!mounted) return

      // Grant admin role to each selected user. Failures are surfaced but the
      // tenant remains mounted — operator can finish admin assignment in
      // TenantUserDialog afterward.
      const failed: string[] = []
      for (const admin of selectedAdmins) {
        const userId = Number(admin.value)
        try {
          await grantTenantAdminApi(mounted.id, userId)
        } catch {
          failed.push(admin.label || `#${userId}`)
        }
      }

      if (failed.length === 0) {
        notification.open({ type: "success", title: String(t("bs:tenant.mountSuccess") ?? ''), description: "" })
      } else {
        notification.open({ type: "warning", title: String(t("bs:tenant.mountSuccess") ?? ''), description: String(t("bs:tenant.adminGrantPartial", {
            names: failed.join(", "),
          }) ?? '') })
      }
      onMounted()
    } catch (error) {
      showApiError(error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>
            {t("bs:tenant.mountTitle")}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <Alert
            type="warning"
            className="[&_p]:line-clamp-none"
            description={t("bs:tenant.mountHint")}
          />

          <div>
            <Label className="text-sm">
              {t("bs:tenant.mountDeptLabel")}
            </Label>
            <div className="mt-1 rounded border bg-muted px-3 py-2 text-sm">
              {deptName}
              <span className="ml-2 text-xs text-muted-foreground">#{deptId}</span>
            </div>
          </div>

          <div>
            <Label htmlFor="tenant_name" className="text-sm">
              {t("bs:tenant.name")}{" "}
              <span className="text-red-500">*</span>
            </Label>
            <Input id="tenant_name" value={tenantName} onChange={(e) => setTenantName(e.target.value)} maxLength={128} className={"mt-1"} showCount />
          </div>

          <div>
            <Label className="text-sm">
              {t("bs:tenant.initialAdmin")}{" "}
              <span className="text-red-500">*</span>
            </Label>
            <div className="mt-1">
              <DepartmentUsersSelect
                multiple
                value={selectedAdmins}
                onChange={setSelectedAdmins}
                rootDeptId={deptId}
                placeholder={t("bs:tenant.initialAdminPlaceholder")}
                searchPlaceholder={t("bs:tenant.searchUser")}
                emptyMessage={t("bs:tenant.initialAdminEmptySubtree")}
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("bs:tenant.initialAdminSubtreeHint")}
            </p>
            {selectedAdmins.length === 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                {t("bs:tenant.initialAdminRequired")}
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outlined" onClick={onClose} disabled={loading} color="default">
            {t("cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={((String((tenantName) ?? '').length > 128)) || (!canSubmit)}>
            {loading
              ? t("bs:tenant.mounting")
              : t("bs:tenant.mountConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
