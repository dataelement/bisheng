import { SubjectSearchUser } from "@/components/bs-comp/permission/SubjectSearchUser"
import type { SelectedSubject } from "@/components/bs-comp/permission/types"
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
  const [adminPicks, setAdminPicks] = useState<SelectedSubject[]>([])
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
      toast({ title: t("bs:department.nameLength"), variant: "error" })
      return
    }
    if (parentId === null) {
      toast({ title: t("bs:department.selectParent"), variant: "error" })
      return
    }
    setLoading(true)
    captureAndAlertRequestErrorHoc(
      createDepartmentApi({
        name,
        parent_id: parentId,
        admin_user_ids: adminPicks.length ? adminPicks.map((s) => s.id) : undefined,
      })
    ).then((res) => {
      setLoading(false)
      if (res !== null) {
        toast({ title: t("bs:department.create"), variant: "success" })
        onCreated()
      }
    })
  }, [name, parentId, adminPicks, onCreated, t])

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

          {/* Department admins (optional) */}
          <div className="space-y-2">
            <Label>{t("bs:department.admins")}</Label>
            <SubjectSearchUser
              value={adminPicks}
              onChange={setAdminPicks}
            />
            {adminPicks.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1">
                {adminPicks.map((s) => (
                  <span
                    key={s.id}
                    className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-xs"
                  >
                    {s.name}
                    <button
                      type="button"
                      className="ml-0.5 text-muted-foreground hover:text-destructive"
                      onClick={() => setAdminPicks((prev) => prev.filter((p) => p.id !== s.id))}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
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
