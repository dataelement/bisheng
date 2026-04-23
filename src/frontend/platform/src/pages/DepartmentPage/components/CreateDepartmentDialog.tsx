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
import { toast } from "@/components/bs-ui/toast/use-toast"
import DepartmentUsersSelect, {
  DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import { createDepartmentApi } from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentTreeNode } from "@/types/api/department"
import { useCallback, useState } from "react"
import { useTranslation } from "react-i18next"

interface CreateDepartmentDialogProps {
  tree: DepartmentTreeNode[]
  defaultParentId: number | null
  onCreated: () => void
  onClose: () => void
}

export function CreateDepartmentDialog({
  tree,
  defaultParentId,
  onCreated,
  onClose,
}: CreateDepartmentDialogProps) {
  const { t } = useTranslation()
  const [name, setName] = useState("")
  const [parentId, setParentId] = useState<number | null>(defaultParentId)
  const [adminSelectValue, setAdminSelectValue] = useState<DepartmentUserOption[]>([])
  const [loading, setLoading] = useState(false)

  // Flatten tree for parent selector (exclude archived departments)
  const flatList: { id: number; name: string; depth: number }[] = []
  const flatten = (nodes: DepartmentTreeNode[], depth: number) => {
    for (const n of nodes) {
      if (n.status === "archived") continue
      flatList.push({ id: n.id, name: n.name, depth })
      if (n.children) flatten(n.children, depth + 1)
    }
  }
  flatten(tree, 0)

  const handleSubmit = useCallback(() => {
    if (!name || name.length < 2 || name.length > 50) {
      toast({
        title: t("prompt"),
        description: t("bs:department.nameLength"),
        variant: "error",
      })
      return
    }
    if (parentId === null) {
      toast({
        title: t("prompt"),
        description: t("bs:department.selectParent"),
        variant: "error",
      })
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
      toast({
        title: t("prompt"),
        description: t("bs:department.create"),
        variant: "success",
      })
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
            <select
              className="w-full rounded-md border px-3 py-2 text-sm"
              value={parentId ?? ""}
              onChange={(e) => setParentId(Number(e.target.value))}
            >
              <option value="" disabled>
                {t("bs:department.selectParent")}
              </option>
              {flatList.map((item) => (
                <option key={item.id} value={item.id}>
                  {"　".repeat(item.depth)}{item.name}
                </option>
              ))}
            </select>
          </div>

          {/* Department name */}
          <div className="space-y-2">
            <Label>{t("bs:department.name")} *</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("bs:department.nameRequired")}
              maxLength={50}
            />
          </div>

          {/* Department admins (optional) — 与部门设置页相同的多选搜索 */}
          <div className="space-y-2">
            <Label>{t("bs:department.admins")}</Label>
            <p className="text-xs text-muted-foreground">{t("bs:department.adminsHint")}</p>
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
          <Button variant="outline" onClick={onClose}>
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
