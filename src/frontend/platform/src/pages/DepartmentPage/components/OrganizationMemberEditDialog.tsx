// @ts-strict-ignore
import { Tooltip as SharedTooltip, TooltipProvider as SharedTooltipProvider } from '@bisheng/ui';
import { Button, Input, Select, notification } from '@bisheng/ui';
import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect"
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"

import { Label } from "@/components/bs-ui/label"


import { cn } from "@/utils"
import {
  applyDepartmentMemberEditApi,
  checkDepartmentMemberDeleteApi,
  deleteDepartmentLocalMemberApi,
  getDepartmentAssignableRolesApi,
  getDepartmentMemberEditFormApi,
  type DepartmentMemberEditForm,
} from "@/controllers/API/department"
import { handleUiRequest, showApiError } from "@/controllers/request"
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
  const selectLabels = useSelectLabels()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<DepartmentMemberEditForm | null>(null)
  const [userName, setUserName] = useState("")
  const [groupSel, setGroupSel] = useState<Set<number>>(new Set())
  const [primaryRoles, setPrimaryRoles] = useState<Set<number>>(new Set())
  const [affRoleByDept, setAffRoleByDept] = useState<Record<string, Set<number>>>({})
  const [ctxRoles, setCtxRoles] = useState<Set<number>>(new Set())
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
    setPrimaryDeptInternalId(null)
    setPrimaryAssignableList([])
  }, [])

  const load = useCallback(async () => {
    if (!member) return
    setLoading(true)
    try {
      const data = await getDepartmentMemberEditFormApi(deptId, member.user_id)
      if (!data) {
        notification.open({ type: "warning", title: String(t("prompt") ?? ''), description: String(t("bs:department.memberEditLoadFailed") ?? '') })
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
    if (open && member) void load().catch(showApiError)
    if (!open) resetLocal()
  }, [open, member, load, resetLocal])

  const handlePrimaryDeptChange = useCallback(
    async (deptInternalId: number | null, node: DepartmentTreeNode | null) => {
      if (deptInternalId == null || !node) return
      setPrimaryDeptInternalId(deptInternalId)
      const rows = await getDepartmentAssignableRolesApi(node.dept_id)
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

  // Role grants are stored per (user, role) with no department dimension, so the
  // per-department dropdowns share one underlying grant. A role offered in several
  // dropdowns — a global role, or a parent-department role also selectable in a
  // child department — is re-granted on save as long as it stays selected in any
  // one of them, which makes it impossible to delete from a single dropdown.
  // Removing it from one dropdown therefore clears it from every other dropdown
  // that also offers it; roles exclusive to one department are left untouched.
  const pruneSharedRoleEverywhere = useCallback(
    (removedIds: number[]) => {
      if (!removedIds.length || !form) return
      const rm = new Set(removedIds)
      const removeOffered = (prev: Set<number>, optionIds: Set<number>) => {
        let changed = false
        const next = new Set(prev)
        rm.forEach((id) => {
          if (optionIds.has(id) && next.delete(id)) changed = true
        })
        return changed ? next : prev
      }
      const primaryOptionIds = new Set(primaryRoleOptions.map((r) => r.id))
      setPrimaryRoles((prev) => removeOffered(prev, primaryOptionIds))
      const ctxOptionIds = new Set(
        (form.assignable_roles_catalog[form.context.dept_id] ?? []).map((r) => r.id)
      )
      setCtxRoles((prev) => removeOffered(prev, ctxOptionIds))
      setAffRoleByDept((prev) => {
        let changed = false
        const next: Record<string, Set<number>> = {}
        for (const [deptKey, sel] of Object.entries(prev)) {
          const optionIds = new Set(
            (form.assignable_roles_catalog[deptKey] ?? []).map((r) => r.id)
          )
          const pruned = removeOffered(sel, optionIds)
          if (pruned !== sel) changed = true
          next[deptKey] = pruned
        }
        return changed ? next : prev
      })
    },
    [form, primaryRoleOptions]
  )

  const handleDeleteLocalMember = useCallback(() => {
    if (!member || !form) return
    bsConfirm({
      desc: t("bs:department.deleteLocalMemberConfirm"),
      onOk: async (close) => {
        const chk = await checkDepartmentMemberDeleteApi(deptId, member.user_id)
        if (chk?.has_assets) {
          const c = chk.counts
          notification.open({ type: "warning", title: String(t("prompt") ?? ''), description: String(t("bs:department.deleteLocalMemberBlocked", {
              k: c.knowledge_spaces,
              f: c.flows,
              a: c.assistants,
            }) ?? '') })
          close()
          return
        }
        await deleteDepartmentLocalMemberApi(deptId, member.user_id)
        notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("bs:department.deleteLocalMemberDone") ?? '') })
        onSaved()
        onClose()
        close()
      },
    })
  }, [deptId, form, member, onClose, onSaved, t])

  const lockedGroupIds = useMemo(
    () => new Set<number>(form?.locked_group_ids ?? []),
    [form]
  )

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
      notification.open({ type: "warning", title: String(t("prompt") ?? ''), description: String(t("bs:department.localUserNameRequired") ?? '') })
      return
    }
    setSaving(true)
    try {
      if (form.edit_mode === "affiliate") {
        await applyDepartmentMemberEditApi(deptId, member.user_id, {
            context_role_ids: Array.from(ctxRoles),
          })
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
          group_ids: Array.from(groupSel).filter(
            (id) => !(form.locked_group_ids ?? []).includes(id)
          ),
          primary_role_ids: Array.from(primaryRoles),
          affiliate_roles,
        }
        await applyDepartmentMemberEditApi(deptId, member.user_id, body)
      }
      notification.open({ type: "success", title: String(t("prompt") ?? ''), description: String(t("bs:department.memberEditSaved") ?? '') })
      onSaved()
      onClose()
    } catch (error) {
      showApiError(error)
    } finally {
      setSaving(false)
    }
  }

  const renderRoleMultiSelect = (
    options: { id: number; role_name: string }[],
    selected: Set<number>,
    onSelectionChange: (next: Set<number>) => void,
    ariaLabel: string
  ) => {
    if (!options.length) {
      return (
        <p className="text-sm text-muted-foreground">{t("bs:department.assignRolesEmptyHint")}</p>
      )
    }
    return (
      <Select
        {...selectLabels}
        multiple
        showSearch
        className="mt-1"
        aria-label={ariaLabel}
        options={options
          .filter((r) => r.id != null)
          .map((r) => ({ label: r.role_name, value: String(r.id) }))}
        value={Array.from(selected).map(String)}
        onChange={(vals) => {
          const next = new Set(vals.map((id) => Number(id)))
          onSelectionChange(next)
          // Sync-delete a removed role from every other dropdown that offers it,
          // so shared/global roles can actually be removed instead of being
          // re-granted on save from another still-selected dropdown.
          const removed = Array.from(selected).filter((id) => !next.has(id))
          pruneSharedRoleEverywhere(removed)
        }}
        placeholder={t("bs:department.multiSelectRolesPlaceholder")}
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
              <Input value={userName} disabled={
                  form.edit_mode === "affiliate" || form.edit_mode === "synced_primary"
                } onChange={(e) => setUserName(e.target.value)} className={"mt-1"} />
            </div>
            <div>
              <Label>{t("bs:department.personId")}</Label>
              <Input readOnly value={form.user.person_id || "-"} className={"mt-1 bg-muted"} />
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
                    <Select
                      {...selectLabels}
                      multiple
                      showSearch
                      className="mt-1"
                      aria-label={t("bs:department.userGroups")}
                      options={form.manageable_groups
                        .filter((g) => g.id != null)
                        .map((g) => ({
                          label: g.group_name,
                          value: String(g.id),
                          // Locked groups cannot be toggled from the panel
                          disabled: lockedGroupIds.has(g.id),
                        }))}
                      value={Array.from(groupSel).map(String)}
                      onChange={(vals) => {
                        // Locked groups stay selected even if removed via a tag or clear
                        const next = new Set(vals.map((id) => Number(id)))
                        groupSel.forEach((id) => {
                          if (lockedGroupIds.has(id)) next.add(id)
                        })
                        setGroupSel(next)
                      }}
                      placeholder={t("bs:department.multiSelectUserGroupsPlaceholder")}
                    />
                  )}
                </div>
                {form.primary_department && (
                  <div>
                    <Label>{t("bs:department.primary")}</Label>
                    {form.can_change_primary && primaryDeptInternalId != null ? (
                      <TreeDepartmentSelect
                        className="mt-1"
                        modal={false}
                        value={primaryDeptInternalId}
                        onChange={handleUiRequest(handlePrimaryDeptChange)}
                        placeholder={t("bs:department.memberEditPrimaryPlaceholder")}
                      />
                    ) : (
                      <>
                        <SharedTooltipProvider delayDuration={300}><SharedTooltip  content={<><p className="break-words text-left text-xs">
                                {form.primary_department.name}
                              </p></>} side="bottom" ><div
                                className={cn(
                                  "mt-1 flex h-9 w-full min-w-0 cursor-default items-center rounded-md border border-input bg-muted px-3 py-1 text-sm text-foreground shadow-sm",
                                )}
                              >
                                <span className="min-w-0 flex-1 truncate">
                                  {form.primary_department.name}
                                </span>
                              </div></SharedTooltip></SharedTooltipProvider>
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
                    {renderRoleMultiSelect(
                      primaryRoleOptions,
                      primaryRoles,
                      setPrimaryRoles,
                      t("bs:department.roles")
                    )}
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
                            setAffRoleByDept((prev) => ({ ...prev, [row.dept_id]: next })),
                          `${row.name} ${t("bs:department.roles")}`
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
                  setCtxRoles,
                  t("bs:department.roles")
                )}
              </div>
            )}
          </div>
        )}
        <DialogFooter className="flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            {form?.edit_mode === "local_primary" && (
              <Button type="button" variant="solid" disabled={saving || loading} onClick={() => handleDeleteLocalMember()} color="danger">
                {t("bs:department.deleteLocalMember")}
              </Button>
            )}
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outlined" onClick={onClose} disabled={saving} color="default">
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
