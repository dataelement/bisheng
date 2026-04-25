import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
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
import MultiSelect from "@/components/bs-ui/select/multi"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  applyDepartmentMemberEditApi,
  checkDepartmentMemberDeleteApi,
  deleteDepartmentLocalMemberApi,
  getDepartmentAssignableRolesApi,
  getDepartmentMemberEditFormApi,
  getDepartmentTreeApi,
  type DepartmentMemberEditForm,
} from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { DepartmentMember, DepartmentTreeNode } from "@/types/api/department"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

type Props = {
  open: boolean
  deptId: string
  member: DepartmentMember | null
  onClose: () => void
  onSaved: () => void
}

export function OrganizationMemberEditDialog({
  open,
  deptId,
  member,
  onClose,
  onSaved,
}: Props) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<DepartmentMemberEditForm | null>(null)
  const [userName, setUserName] = useState("")
  const [groupSel, setGroupSel] = useState<Set<number>>(new Set())
  const [primaryRoles, setPrimaryRoles] = useState<Set<number>>(new Set())
  const [affRoleByDept, setAffRoleByDept] = useState<Record<string, Set<number>>>({})
  const [ctxRoles, setCtxRoles] = useState<Set<number>>(new Set())
  const [treeNodes, setTreeNodes] = useState<DepartmentTreeNode[]>([])
  const [primaryDeptInternalId, setPrimaryDeptInternalId] = useState<number | null>(null)
  const [primaryAssignableList, setPrimaryAssignableList] = useState<
    { id: number; role_name: string }[]
  >([])

  const resetLocal = useCallback(() => {
    setForm(null)
    setUserName("")
    setGroupSel(new Set())
    setPrimaryRoles(new Set())
    setAffRoleByDept({})
    setCtxRoles(new Set())
    setTreeNodes([])
    setPrimaryDeptInternalId(null)
    setPrimaryAssignableList([])
  }, [])

  const load = useCallback(async () => {
    if (!member) return
    setLoading(true)
    try {
      const data = await captureAndAlertRequestErrorHoc(
        getDepartmentMemberEditFormApi(deptId, member.user_id)
      )
      if (!data) {
        toast({
          title: t("prompt"),
          variant: "warning",
          description: t("bs:department.memberEditLoadFailed"),
        })
        return
      }
      setForm(data)
      setUserName(data.user.user_name)
      setGroupSel(new Set(data.current_group_ids))
      if (data.edit_mode === "affiliate") {
        setCtxRoles(new Set(data.context_role_ids))
      } else {
        const pr = new Set(data.primary_department?.role_ids ?? [])
        setPrimaryRoles(pr)
        const m: Record<string, Set<number>> = {}
        for (const row of data.affiliate_rows) {
          m[row.dept_id] = new Set(row.role_ids)
        }
        setAffRoleByDept(m)
        if (data.can_change_primary && data.primary_department?.id != null) {
          setPrimaryDeptInternalId(data.primary_department.id)
          const key = data.primary_department.dept_id
          setPrimaryAssignableList(
            (data.assignable_roles_catalog[key] ?? []).map((r) => ({
              id: r.id,
              role_name: r.role_name,
            }))
          )
          const tree = await captureAndAlertRequestErrorHoc(getDepartmentTreeApi())
          setTreeNodes(Array.isArray(tree) ? tree : [])
        } else {
          setPrimaryDeptInternalId(null)
          setPrimaryAssignableList(
            (data.primary_department
              ? data.assignable_roles_catalog[data.primary_department.dept_id] ?? []
              : []
            ).map((r) => ({ id: r.id, role_name: r.role_name }))
          )
        }
      }
    } finally {
      setLoading(false)
    }
  }, [deptId, member, t])

  useEffect(() => {
    if (open && member) void load()
    if (!open) resetLocal()
  }, [open, member, load, resetLocal])

  const handlePrimaryDeptChange = useCallback(
    async (deptInternalId: number | null, node: DepartmentTreeNode | null) => {
      if (deptInternalId == null || !node) return
      setPrimaryDeptInternalId(deptInternalId)
      const rows = await captureAndAlertRequestErrorHoc(
        getDepartmentAssignableRolesApi(node.dept_id)
      )
      const list = Array.isArray(rows) ? rows : []
      setPrimaryAssignableList(list.map((r: { id: number; role_name: string }) => ({
        id: r.id,
        role_name: r.role_name,
      })))
      setPrimaryRoles((prev) => {
        const allowed = new Set(list.map((r: { id: number }) => r.id))
        return new Set([...prev].filter((rid) => allowed.has(rid)))
      })
    },
    []
  )

  const primaryRoleOptions = useMemo(() => {
    if (!form || form.edit_mode === "affiliate") return []
    if (primaryAssignableList.length) return primaryAssignableList
    const key = form.primary_department?.dept_id
    if (!key) return []
    return (form.assignable_roles_catalog[key] ?? []).map((r) => ({
      id: r.id,
      role_name: r.role_name,
    }))
  }, [form, primaryAssignableList])

  const handleDeleteLocalMember = useCallback(() => {
    if (!member || !form) return
    bsConfirm({
      desc: t("bs:department.deleteLocalMemberConfirm"),
      onOk: async (close) => {
        const chk = await captureAndAlertRequestErrorHoc(
          checkDepartmentMemberDeleteApi(deptId, member.user_id)
        )
        if (chk === false) {
          close()
          return
        }
        if (chk?.has_assets) {
          const c = chk.counts
          toast({
            title: t("prompt"),
            variant: "warning",
            description: t("bs:department.deleteLocalMemberBlocked", {
              k: c.knowledge_spaces,
              f: c.flows,
              a: c.assistants,
            }),
          })
          close()
          return
        }
        const delRes = await captureAndAlertRequestErrorHoc(
          deleteDepartmentLocalMemberApi(deptId, member.user_id)
        )
        if (delRes === false) {
          close()
          return
        }
        toast({
          title: t("prompt"),
          variant: "success",
          description: t("bs:department.deleteLocalMemberDone"),
        })
        onSaved()
        onClose()
        close()
      },
    })
  }, [deptId, form, member, onClose, onSaved, t])

  const title = useMemo(() => {
    if (!form) return t("edit")
    if (form.edit_mode === "affiliate") return t("bs:department.memberEditTitleAffiliate")
    if (form.edit_mode === "synced_primary")
      return t("bs:department.memberEditTitleSynced")
    return t("bs:department.memberEditTitleLocal")
  }, [form, t])

  const handleSave = async () => {
    if (!member || !form) return
    if (form.edit_mode === "local_primary" && !userName.trim()) {
      toast({
        title: t("prompt"),
        variant: "warning",
        description: t("bs:department.localUserNameRequired"),
      })
      return
    }
    setSaving(true)
    try {
      if (form.edit_mode === "affiliate") {
        const res = await captureAndAlertRequestErrorHoc(
          applyDepartmentMemberEditApi(deptId, member.user_id, {
            context_role_ids: Array.from(ctxRoles),
          })
        )
        if (res === false) return
      } else {
        const affiliate_roles = (form.affiliate_rows ?? []).map((row) => ({
          dept_id: row.dept_id,
          role_ids: Array.from(affRoleByDept[row.dept_id] ?? new Set()),
        }))
        const body: Parameters<typeof applyDepartmentMemberEditApi>[2] = {
          user_name: form.edit_mode === "local_primary" ? userName.trim() : undefined,
          primary_department_id:
            form.edit_mode === "local_primary" &&
            form.can_change_primary &&
            primaryDeptInternalId != null
              ? primaryDeptInternalId
              : undefined,
          group_ids: Array.from(groupSel),
          primary_role_ids: Array.from(primaryRoles),
          affiliate_roles,
        }
        const res = await captureAndAlertRequestErrorHoc(
          applyDepartmentMemberEditApi(deptId, member.user_id, body)
        )
        if (res === false) return
      }
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("bs:department.memberEditSaved"),
      })
      onSaved()
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const renderRoleMultiSelect = (
    options: { id: number; role_name: string }[],
    selected: Set<number>,
    onSelectionChange: (next: Set<number>) => void
  ) => {
    if (!options.length) {
      return (
        <p className="text-sm text-muted-foreground">{t("bs:department.assignRolesEmptyHint")}</p>
      )
    }
    return (
      <MultiSelect
        multiple
        className="mt-1"
        options={options.map((r) => ({ label: r.role_name, value: String(r.id) }))}
        value={Array.from(selected).map(String)}
        onChange={(vals) => onSelectionChange(new Set((vals as string[]).map((id) => Number(id))))}
        placeholder={t("bs:department.multiSelectRolesPlaceholder")}
        searchPlaceholder={t("system.searchRoles")}
      />
    )
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-lg"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        {loading || !form ? (
          <div className="py-10 text-center text-muted-foreground">
            {t("bs:department.memberEditLoading")}
          </div>
        ) : (
          <div className="space-y-4 py-1">
            <div>
              <Label>{t("system.username")}</Label>
              <Input
                className="mt-1"
                value={userName}
                disabled={
                  form.edit_mode === "affiliate" || form.edit_mode === "synced_primary"
                }
                onChange={(e) => setUserName(e.target.value)}
              />
            </div>
            <div>
              <Label>{t("bs:department.personId")}</Label>
              <Input className="mt-1 bg-muted" readOnly value={form.user.person_id || "-"} />
            </div>

            {form.edit_mode !== "affiliate" && (
              <>
                <div>
                  <Label>{t("bs:department.userGroups")}</Label>
                  {form.manageable_groups.length === 0 ? (
                    <p className="mt-1 text-sm text-muted-foreground">
                      {t("bs:department.memberEditUserGroupsEmpty")}
                    </p>
                  ) : (
                    <MultiSelect
                      multiple
                      className="mt-1"
                      options={form.manageable_groups.map((g) => ({
                        label: g.group_name,
                        value: String(g.id),
                      }))}
                      value={Array.from(groupSel).map(String)}
                      onChange={(vals) =>
                        setGroupSel(new Set((vals as string[]).map((id) => Number(id))))
                      }
                      placeholder={t("bs:department.multiSelectUserGroupsPlaceholder")}
                      searchPlaceholder={t("system.searchUserGroups")}
                    />
                  )}
                </div>
                {form.primary_department && (
                  <div>
                    <Label>{t("bs:department.primary")}</Label>
                    {form.can_change_primary && primaryDeptInternalId != null ? (
                      <>
                        <TreeDepartmentSelect
                          className="mt-1"
                          modal={false}
                          nodes={treeNodes}
                          value={primaryDeptInternalId}
                          onChange={(id, node) => void handlePrimaryDeptChange(id, node)}
                          placeholder={t("bs:department.memberEditPrimaryPlaceholder")}
                          showMemberCount
                        />
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t("bs:department.memberEditPrimaryHint")}
                        </p>
                      </>
                    ) : (
                      <>
                        <Input
                          className="mt-1 bg-muted"
                          readOnly
                          value={form.primary_department.name}
                        />
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t("bs:department.memberEditPrimaryReadonly")}
                        </p>
                      </>
                    )}
                  </div>
                )}
                {form.primary_department && (
                  <div>
                    <Label>{t("bs:department.roles")}</Label>
                    {renderRoleMultiSelect(primaryRoleOptions, primaryRoles, setPrimaryRoles)}
                  </div>
                )}
                {form.affiliate_rows.length > 0 && (
                  <div className="space-y-3">
                    <Label>{t("bs:department.memberEditAffiliateSection")}</Label>
                    {form.affiliate_rows.map((row) => (
                      <div key={row.dept_id} className="rounded border p-3">
                        <div className="mb-2 text-sm font-medium">{row.name}</div>
                        {renderRoleMultiSelect(
                          form.assignable_roles_catalog[row.dept_id] ?? [],
                          affRoleByDept[row.dept_id] ?? new Set(),
                          (next) =>
                            setAffRoleByDept((prev) => ({ ...prev, [row.dept_id]: next }))
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            {form.edit_mode === "affiliate" && (
              <div>
                <Label>{t("bs:department.roles")}</Label>
                {renderRoleMultiSelect(
                  form.assignable_roles_catalog[form.context.dept_id] ?? [],
                  ctxRoles,
                  setCtxRoles
                )}
              </div>
            )}
          </div>
        )}
        <DialogFooter className="flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            {form?.edit_mode === "local_primary" && (
              <Button
                type="button"
                variant="destructive"
                disabled={saving || loading}
                onClick={() => handleDeleteLocalMember()}
              >
                {t("bs:department.deleteLocalMember")}
              </Button>
            )}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose} disabled={saving}>
              {t("cancel")}
            </Button>
            <Button onClick={() => void handleSave()} disabled={saving || loading || !form}>
              {t("save")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
