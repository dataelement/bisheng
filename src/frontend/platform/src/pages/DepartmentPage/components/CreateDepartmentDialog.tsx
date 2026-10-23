import { Button, Input, notification } from '@bisheng/ui';

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"

import { Label } from "@/components/bs-ui/label"

import { TreeDepartmentSelect } from "@/components/bs-comp/department"
import DepartmentUsersSelect, {
  DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { createDepartmentApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useCallback, useState } from "react"
import { useTranslation } from "react-i18next"

interface CreateDepartmentDialogProps {
  defaultParentId: number | null
  onCreated: () => void
  onClose: () => void
}

export function CreateDepartmentDialog({
  defaultParentId,
  onCreated,
  onClose,
}: CreateDepartmentDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState("")
  const [parentId, setParentId] = useState<number | null>(defaultParentId)
  const [adminSelectValue, setAdminSelectValue] = useState<DepartmentUserOption[]>([])
  const [loading, setLoading] = useState(false)

  const handleSubmit = useCallback(() => {
    if (!name || name.length < 2 || name.length > 50) {
      notification.open({ type: "error", title: String(t("prompt") ?? ''), description: String(t("bs:department.nameLength") ?? '') })
      return
    }
    if (parentId === null) {
      notification.open({ type: "error", title: String(t("prompt") ?? ''), description: String(t("bs:department.selectParent") ?? '') })
      return
    }
    setLoading(true)
    captureAndAlertRequestErrorHoc(
      createDepartmentApi({
        name,
        parent_id: parentId,
        admin_user_ids: adminSelectValue.length
          ? adminSelectValue.map((o) => o.value)
          : undefined,
      })
    ).then((res) => {
      setLoading(false)
      // captureAndAlertRequestErrorHoc 在接口失败时返回 false（不是 null）
      if (res === false) return
      notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("bs:department.create") ?? '') })
      onCreated()
    })
  }, [name, parentId, adminSelectValue, onCreated, t])

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("bs:department.create")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {/* Parent department */}
          <div className="space-y-2">
            <Label>{t("bs:department.parentDept")} *</Label>
            <TreeDepartmentSelect
              value={parentId}
              onChange={(id) => setParentId(id)}
              modal={false}
              placeholder={t("bs:department.selectParent")}
              searchPlaceholder={t("bs:department.search")}
              className="max-w-xl"
            />
          </div>

          {/* Department name */}
          <div className="space-y-2">
            <Label>{t("bs:department.name")} *</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("bs:department.nameRequired")} maxLength={50} showCount />
          </div>

          {/* Department admins (optional) — 与部门设置页相同的多选搜索 */}
          <div className="space-y-2">
            <Label>{t("bs:department.admins")}</Label>
            <DepartmentUsersSelect
              multiple
              value={adminSelectValue}
              onChange={(vals) => {
                const v = (vals as DepartmentUserOption[]) || []
                setAdminSelectValue(v)
              }}
              placeholder={t("bs:department.adminSelectPlaceholder")}
              searchPlaceholder={t("bs:department.searchUsersPlaceholder")}
              className="max-w-xl w-full"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outlined" onClick={onClose} color="default">
            {t("cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={loading}>
            {t("confirmButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
