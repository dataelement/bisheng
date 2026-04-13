import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  deleteDepartmentApi,
  getDepartmentAdminsApi,
  setDepartmentAdminsApi,
  updateDepartmentApi,
} from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentAdmin, DepartmentTreeNode } from "@/types/api/department"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface DepartmentSettingsProps {
  dept: DepartmentTreeNode
  tree: DepartmentTreeNode[]
  onChanged: () => void
}

export function DepartmentSettings({ dept, tree, onChanged }: DepartmentSettingsProps) {
  const { t } = useTranslation()
  const [name, setName] = useState(dept.name)
  const [admins, setAdmins] = useState<DepartmentAdmin[]>([])
  const [adminInput, setAdminInput] = useState("")
  const isSynced = dept.source !== "local"

  useEffect(() => {
    setName(dept.name)
    // Load admins
    captureAndAlertRequestErrorHoc(getDepartmentAdminsApi(dept.dept_id)).then(
      (res) => {
        if (res) setAdmins(res)
      }
    )
  }, [dept.dept_id])

  const handleSaveName = useCallback(() => {
    if (!name || name.length < 2 || name.length > 50) {
      toast({ title: t("bs:department.nameLength"), variant: "error" })
      return
    }
    captureAndAlertRequestErrorHoc(
      updateDepartmentApi(dept.dept_id, { name })
    ).then((res) => {
      if (res !== null) {
        toast({ title: t("prompt"), variant: "success" })
        onChanged()
      }
    })
  }, [dept.dept_id, name, onChanged, t])

  const handleRemoveAdmin = useCallback(
    (userId: number) => {
      const newIds = admins.filter((a) => a.user_id !== userId).map((a) => a.user_id)
      captureAndAlertRequestErrorHoc(
        setDepartmentAdminsApi(dept.dept_id, newIds)
      ).then((res) => {
        if (res) setAdmins(res)
      })
    },
    [dept.dept_id, admins]
  )

  const handleDelete = useCallback(() => {
    bsConfirm({
      title: t("bs:department.delete"),
      desc: t("bs:department.confirmDelete"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(
          deleteDepartmentApi(dept.dept_id)
        ).then((res) => {
          if (res !== null) {
            toast({ title: t("bs:department.delete"), variant: "success" })
            onChanged()
          }
          next()
        })
      },
    })
  }, [dept.dept_id, onChanged, t])

  // Find parent name
  const findParentName = (
    nodes: DepartmentTreeNode[],
    parentId: number | null
  ): string => {
    if (parentId === null) return "-"
    for (const n of nodes) {
      if (n.id === parentId) return n.name
      const found = findParentName(n.children || [], parentId)
      if (found !== "-") return found
    }
    return "-"
  }

  return (
    <div className="max-w-lg space-y-6">
      {/* Department Name */}
      <div className="space-y-2">
        <Label>{t("bs:department.name")}</Label>
        {isSynced ? (
          <div>
            <Input value={name} disabled />
            <p className="mt-1 text-xs text-muted-foreground">
              {t("bs:department.readonlyField")}
            </p>
          </div>
        ) : (
          <div className="flex gap-2">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={50}
            />
            <Button size="sm" onClick={handleSaveName}>
              {t("save")}
            </Button>
          </div>
        )}
      </div>

      {/* Parent Department */}
      <div className="space-y-2">
        <Label>{t("bs:department.parentDept")}</Label>
        <Input value={findParentName(tree, dept.parent_id)} disabled />
      </div>

      {/* Department ID */}
      <div className="space-y-2">
        <Label>{t("bs:department.deptId")}</Label>
        <Input value={dept.dept_id} disabled />
      </div>

      {/* Admins */}
      <div className="space-y-2">
        <Label>{t("bs:department.admins")}</Label>
        <div className="flex flex-wrap gap-2">
          {admins.length === 0 ? (
            <span className="text-sm text-muted-foreground">-</span>
          ) : (
            admins.map((a) => (
              <span
                key={a.user_id}
                className="inline-flex items-center gap-1 rounded-full bg-accent px-3 py-1 text-sm"
              >
                {a.user_name}
                <button
                  className="ml-1 text-muted-foreground hover:text-destructive"
                  onClick={() => handleRemoveAdmin(a.user_id)}
                >
                  ×
                </button>
              </span>
            ))
          )}
        </div>
      </div>

      {/* Delete */}
      {!isSynced && dept.parent_id !== null && (
        <div className="border-t pt-6">
          <Button variant="destructive" onClick={handleDelete}>
            {t("bs:department.delete")}
          </Button>
        </div>
      )}
    </div>
  )
}
