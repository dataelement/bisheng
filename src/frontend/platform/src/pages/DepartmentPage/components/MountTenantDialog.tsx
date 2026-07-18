import { Button } from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { mountTenantApi } from "@/controllers/API/department"
import { grantTenantAdminApi } from "@/controllers/API/tenant"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
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
    if (!canSubmit) return
    setLoading(true)
    try {
      const mounted = await captureAndAlertRequestErrorHoc(
        mountTenantApi(deptId, {
          tenant_name: tenantName.trim(),
        })
      )
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
        toast({
          title: t("bs:tenant.mountSuccess", { defaultValue: "挂载成功" }),
          variant: "success",
        })
      } else {
        toast({
          title: t("bs:tenant.mountSuccess", { defaultValue: "挂载成功" }),
          description: t("bs:tenant.adminGrantPartial", {
            defaultValue: "以下用户未能授予管理员，请在成员管理中重试: {{names}}",
            names: failed.join(", "),
          }),
          variant: "warning",
        })
      }
      onMounted()
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>
            {t("bs:tenant.mountTitle", { defaultValue: "标记为子租户" })}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950 dark:text-amber-100">
            {t("bs:tenant.mountHint", {
              defaultValue:
                "将该部门及其子树标记为独立子租户。挂载后该子树下的资源、配额、权限独立于 Root，操作不可撤销（解绑可在租户管理中执行）。",
            })}
          </div>

          <div>
            <Label className="text-sm">
              {t("bs:tenant.mountDeptLabel", { defaultValue: "目标部门" })}
            </Label>
            <div className="mt-1 rounded border bg-muted px-3 py-2 text-sm">
              {deptName}
              <span className="ml-2 text-xs text-muted-foreground">#{deptId}</span>
            </div>
          </div>

          <div>
            <Label htmlFor="tenant_name" className="text-sm">
              {t("bs:tenant.name", { defaultValue: "租户名称" })}{" "}
              <span className="text-red-500">*</span>
            </Label>
            <Input
              id="tenant_name"
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              maxLength={128}
              className="mt-1"
            />
          </div>

          <div>
            <Label className="text-sm">
              {t("bs:tenant.initialAdmin", { defaultValue: "初始管理员" })}{" "}
              <span className="text-red-500">*</span>
            </Label>
            <div className="mt-1">
              <DepartmentUsersSelect
                multiple
                value={selectedAdmins}
                onChange={setSelectedAdmins}
                rootDeptId={deptId}
                placeholder={t("bs:tenant.initialAdminPlaceholder", {
                  defaultValue: "搜索用户名添加",
                })}
                searchPlaceholder={t("bs:tenant.searchUser", {
                  defaultValue: "搜索用户",
                })}
                emptyMessage={t("bs:tenant.initialAdminEmptySubtree", {
                  defaultValue: "该部门子树暂无成员，请先把目标管理员加入此部门后再挂载",
                })}
              />
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("bs:tenant.initialAdminSubtreeHint", {
                defaultValue:
                  "管理员必须来自该部门子树，不能选取子树外用户。",
              })}
            </p>
            {selectedAdmins.length === 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                {t("bs:tenant.initialAdminRequired", {
                  defaultValue: "请至少指定一位初始管理员",
                })}
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            {t("cancel", { defaultValue: "取消" })}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {loading
              ? t("bs:tenant.mounting", { defaultValue: "挂载中..." })
              : t("bs:tenant.mountConfirm", { defaultValue: "确认挂载" })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
