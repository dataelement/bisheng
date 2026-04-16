import { SubjectSearchUser } from "@/components/bs-comp/permission/SubjectSearchUser"
import type { SelectedSubject } from "@/components/bs-comp/permission/types"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import MultiSelect from "@/components/bs-ui/select/multi"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  deleteDepartmentApi,
  getDepartmentAdminsApi,
  getDepartmentApi,
  getDepartmentAssignableRolesApi,
  purgeDepartmentApi,
  setDepartmentAdminsApi,
  updateDepartmentApi,
} from "@/controllers/API/department"
import { isSyncedSource } from "@/pages/DepartmentPage/constants/syncReadonly"
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
  const [pendingAdminPick, setPendingAdminPick] = useState<SelectedSubject[]>([])
  const [defaultRoleIds, setDefaultRoleIds] = useState<string[]>([])
  const [assignableRoles, setAssignableRoles] = useState<{ value: string; label: string }[]>([])
  const isSynced = isSyncedSource(dept.source)

  useEffect(() => {
    setName(dept.name)
    // Load admins
    captureAndAlertRequestErrorHoc(getDepartmentAdminsApi(dept.dept_id)).then(
      (res) => {
        if (res) setAdmins(res)
      }
    )
    // Load default roles
    captureAndAlertRequestErrorHoc(getDepartmentApi(dept.dept_id)).then(
      (res) => {
        if (res) setDefaultRoleIds((res.default_role_ids ?? []).map(String))
      }
    )
    // Load assignable roles
    captureAndAlertRequestErrorHoc(getDepartmentAssignableRolesApi(dept.dept_id)).then(
      (res) => {
        if (res) setAssignableRoles(res.map((r) => ({ value: String(r.id), label: r.role_name })))
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
        if (Array.isArray(res)) {
          setAdmins(res)
          toast({ title: t("prompt"), variant: "success" })
        }
      })
    },
    [dept.dept_id, admins, t]
  )

  const handleAddAdmins = useCallback(() => {
    if (!pendingAdminPick.length) {
      toast({
        title: t("prompt"),
        variant: "warning",
        description: t("bs:department.pickAdminFirst"),
      })
      return
    }
    const existing = new Set(admins.map((a) => a.user_id))
    const merged = [
      ...admins.map((a) => a.user_id),
      ...pendingAdminPick.map((s) => s.id).filter((id) => !existing.has(id)),
    ]
    captureAndAlertRequestErrorHoc(
      setDepartmentAdminsApi(dept.dept_id, merged)
    ).then((res) => {
      if (Array.isArray(res)) {
        setAdmins(res)
        setPendingAdminPick([])
        toast({ title: t("prompt"), variant: "success" })
        onChanged()
      }
    })
  }, [admins, dept.dept_id, onChanged, pendingAdminPick, t])

  const handleSaveDefaultRoles = useCallback(() => {
    captureAndAlertRequestErrorHoc(
      updateDepartmentApi(dept.dept_id, { default_role_ids: defaultRoleIds.map(Number) })
    ).then((res) => {
      if (res !== null) {
        toast({ title: t("prompt"), variant: "success" })
      }
    })
  }, [dept.dept_id, defaultRoleIds, t])

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

  const handlePurge = useCallback(() => {
    bsConfirm({
      title: t("bs:department.permanentDelete"),
      desc: t("bs:department.confirmPermanentDelete"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(
          purgeDepartmentApi(dept.dept_id)
        ).then((res) => {
          if (res !== null) {
            toast({ title: t("bs:department.permanentDelete"), variant: "success" })
            onChanged()
          }
          next()
        })
      },
    })
  }, [dept.dept_id, onChanged, t])

  const isArchived = dept.status === "archived"

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
      {isArchived && (
        <div className="rounded-md border border-orange-200 bg-orange-50 p-3 text-sm text-orange-800 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-200">
          {t("bs:department.archivedNotice")}
        </div>
      )}

      {/* Department Name */}
      <div className="space-y-2">
        <Label>{t("bs:department.name")}</Label>
        {isSynced || isArchived ? (
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

      {/* Admins */}
      {!isArchived && (
      <div className="space-y-2">
        <Label>{t("bs:department.admins")}</Label>
        <p className="text-xs text-muted-foreground">
          {t("bs:department.adminsHint")}
        </p>
        <SubjectSearchUser
          value={pendingAdminPick}
          onChange={setPendingAdminPick}
        />
        <Button type="button" size="sm" variant="secondary" onClick={handleAddAdmins}>
          {t("bs:department.addAdmins")}
        </Button>
        <div className="flex flex-wrap gap-2 pt-1">
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
                  type="button"
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
      )}

      {/* Default Roles */}
      {!isArchived && (
      <div className="space-y-2">
        <Label>{t("bs:department.defaultRoles")}</Label>
        <p className="text-xs text-muted-foreground">
          {t("bs:department.defaultRolesHint")}
        </p>
        <MultiSelect
          multiple
          value={defaultRoleIds}
          options={assignableRoles}
          placeholder={t("bs:department.selectRoles")}
          onChange={(vals) => setDefaultRoleIds(vals as string[])}
        />
        <Button type="button" size="sm" onClick={handleSaveDefaultRoles}>
          {t("save")}
        </Button>
      </div>
      )}

      {/* Delete / Purge */}
      {isArchived && (
        <div className="border-t pt-6">
          <Button variant="destructive" onClick={handlePurge}>
            {t("bs:department.permanentDelete")}
          </Button>
        </div>
      )}
      {!isArchived && !isSynced && dept.parent_id !== null && (
        <div className="border-t pt-6">
          <Button variant="destructive" onClick={handleDelete}>
            {t("bs:department.delete")}
          </Button>
        </div>
      )}
    </div>
  )
}
