import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import MultiSelect from "@/components/bs-ui/select/multi"
import { Separator } from "@/components/bs-ui/separator"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect"
import DepartmentUsersSelect, {
  DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect"
import {
  deleteDepartmentApi,
  getDepartmentAdminsApi,
  getDepartmentApi,
  getDepartmentAssignableRolesApi,
  moveDepartmentApi,
  purgeDepartmentApi,
  restoreDepartmentApi,
  setDepartmentCompanyRootApi,
  clearDepartmentCompanyRootApi,
  unmountTenantApi,
  updateDepartmentApi,
} from "@/controllers/API/department"
import { isGuestDepartmentDeptId } from "@/pages/DepartmentPage/constants/systemDepartments"
import { isSyncedSource } from "@/pages/DepartmentPage/constants/syncReadonly"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { DepartmentAdmin, DepartmentTreeNode } from "@/types/api/department"
import { Building2 } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

interface DepartmentSettingsProps {
  dept: DepartmentTreeNode
  tree: DepartmentTreeNode[]
  onChanged: (removedDeptId?: string) => void
  /** Open the "mark as Child Tenant" dialog for this department. When undefined
   * (multi-tenant disabled or root dept), the action button is hidden. */
  onMarkAsTenant?: (deptId: number, deptName: string) => void
  /** F070 当前节点 org_level；null 表示未打标（未落入任何公司子树） */
  orgLevel?: string | null
  /** 仅平台超管可设公司根 */
  canSetCompanyRoot?: boolean
  /** 打标成功后刷新树侧徽章 */
  onOrgLevelChanged?: () => void
}

function adminsToOptions(admins: DepartmentAdmin[]): DepartmentUserOption[] {
  return admins.map((a) => ({ value: Number(a.user_id), label: a.user_name }))
}

function sameIdSet(left: Array<number | string>, right: Array<number | string>): boolean {
  if (left.length !== right.length) return false
  const leftIds = left.map(String).sort()
  const rightIds = right.map(String).sort()
  return leftIds.every((id, idx) => id === rightIds[idx])
}

/** 企业级表单：统一控件最大宽度，右侧对齐 */
const FORM_CONTROL_WIDTH = "w-full max-w-md"
/** Radix Select 不接受空串；用哨兵表示「未设置/取消公司」。 */
const ORG_LEVEL_UNSET = "__unset__"

type OrgLevelDraft = "company" | typeof ORG_LEVEL_UNSET

function toOrgLevelDraft(level: string | null | undefined): OrgLevelDraft {
  return level === "company" ? "company" : ORG_LEVEL_UNSET
}

export function DepartmentSettings({
  dept,
  tree,
  onChanged,
  onMarkAsTenant,
  orgLevel = null,
  canSetCompanyRoot = false,
  onOrgLevelChanged,
}: DepartmentSettingsProps) {
  const { t } = useTranslation()
  const [name, setName] = useState(dept.name)
  const [adminSelectValue, setAdminSelectValue] = useState<DepartmentUserOption[]>([])
  const [defaultRoleIds, setDefaultRoleIds] = useState<string[]>([])
  const [applyDefaultRolesToExisting, setApplyDefaultRolesToExisting] = useState(false)
  const [assignableRoles, setAssignableRoles] = useState<{ value: string; label: string }[]>([])
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [parentIdValue, setParentIdValue] = useState<number | null>(dept.parent_id ?? null)
  const [parentTreeNodes, setParentTreeNodes] = useState<DepartmentTreeNode[]>([])
  const [isDefaultRootDept, setIsDefaultRootDept] = useState(Boolean(dept.is_default_root))
  const [orgLevelDraft, setOrgLevelDraft] = useState<OrgLevelDraft>(() => toOrgLevelDraft(orgLevel))

  const adminSelectValueRef = useRef<DepartmentUserOption[]>([])

  const isSynced = isSyncedSource(dept.source)
  const isArchived = dept.status === "archived"
  /** 仅部门名称对第三方同步部门只读；管理员、默认角色与上级部门仍可保存 */
  const canEditName = !isArchived && !isSynced
  const canEditPermissions = !isArchived
  const canEditParent = !isArchived && !isDefaultRootDept

  /**
   * 可编辑：未落入任何公司子树（未打标），或当前就是公司根（可清除）。
   * 同级可另设公司；子树内自动标注节点只读。
   */
  const canEditOrgLevel = useMemo(() => {
    if (!canSetCompanyRoot) return false
    if (orgLevel === "company") return true
    return orgLevel == null
  }, [canSetCompanyRoot, orgLevel])

  const orgLevelDisabledReason = useMemo(() => {
    if (!canSetCompanyRoot || canEditOrgLevel) return null
    if (orgLevel != null && orgLevel !== "company") return "underSubtree" as const
    return null
  }, [canEditOrgLevel, canSetCompanyRoot, orgLevel])

  /** 最近一次从服务端加载成功的快照（父部门变更判断、保存后更新） */
  const baselineRef = useRef<{
    name: string
    admins: DepartmentUserOption[]
    defaultRoleIds: string[]
    parentId: number | null
    orgLevelDraft: OrgLevelDraft
  } | null>(null)

  useEffect(() => {
    adminSelectValueRef.current = adminSelectValue
  }, [adminSelectValue])

  // 切换部门或服务端标签刷新时，重置草稿并写入 baseline。
  useEffect(() => {
    const draft = toOrgLevelDraft(orgLevel)
    setOrgLevelDraft(draft)
    if (baselineRef.current) {
      baselineRef.current = { ...baselineRef.current, orgLevelDraft: draft }
    }
  }, [dept.dept_id, orgLevel])

  const gatherSubtreeIds = useCallback((node: DepartmentTreeNode | null): Set<number> => {
    const ids = new Set<number>()
    if (!node) return ids
    const walk = (n: DepartmentTreeNode) => {
      ids.add(n.id)
      for (const c of n.children || []) walk(c)
    }
    walk(node)
    return ids
  }, [])

  const findNodeByDeptId = useCallback(
    (nodes: DepartmentTreeNode[], deptId: string): DepartmentTreeNode | null => {
      for (const n of nodes) {
        if (n.dept_id === deptId) return n
        const found = findNodeByDeptId(n.children || [], deptId)
        if (found) return found
      }
      return null
    },
    []
  )

  const buildParentTreeNodes = useCallback(
    (nodes: DepartmentTreeNode[], selectedDeptId: string): DepartmentTreeNode[] => {
      const selectedNode = findNodeByDeptId(nodes, selectedDeptId)
      const excluded = gatherSubtreeIds(selectedNode)
      const walk = (n: DepartmentTreeNode): DepartmentTreeNode | null => {
        // 仅可挂到当前可见树（入参 nodes）中的 active 节点；且不能选自身/子树
        if (excluded.has(n.id) || n.status !== "active") return null
        const nextChildren = (n.children || [])
          .map((c) => walk(c))
          .filter((x): x is DepartmentTreeNode => Boolean(x))
        return {
          ...n,
          children: nextChildren,
        }
      }
      return nodes
        .map((root) => walk(root))
        .filter((x): x is DepartmentTreeNode => Boolean(x))
    },
    [findNodeByDeptId, gatherSubtreeIds]
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setApplyDefaultRolesToExisting(false)
    Promise.all([
      getDepartmentAdminsApi(dept.dept_id),
      getDepartmentApi(dept.dept_id),
      getDepartmentAssignableRolesApi(dept.dept_id),
    ])
      .then(([adminsRes, detailRes, rolesRes]) => {
        if (cancelled) return
        const adm = Array.isArray(adminsRes) ? adminsRes : []
        const adminOpts = adminsToOptions(adm)
        setAdminSelectValue(adminOpts)
        adminSelectValueRef.current = adminOpts
        setName(detailRes?.name ?? dept.name)
        const dr = (detailRes?.default_role_ids ?? []).map(String)
        setDefaultRoleIds(dr)
        const pTreeNodes = buildParentTreeNodes(tree, dept.dept_id)
        setParentTreeNodes(pTreeNodes)
        const pid = detailRes?.parent_id ?? dept.parent_id ?? null
        setParentIdValue(pid)
        setIsDefaultRootDept(Boolean(detailRes?.is_default_root ?? dept.is_default_root))
        setAssignableRoles(
          (rolesRes || []).map((r) => ({ value: String(r.id), label: r.role_name }))
        )
        baselineRef.current = {
          name: detailRes?.name ?? dept.name,
          admins: adminOpts,
          defaultRoleIds: dr,
          parentId: pid,
          orgLevelDraft: toOrgLevelDraft(orgLevel),
        }
      })
      .catch(() => {
        if (!cancelled) {
          toast({
            title: t("prompt"),
            variant: "error",
            description: t("bs:department.settingsLoadFailed"),
          })
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // orgLevel 草稿由下方独立 effect 同步，避免标签刷新时整表重载。
  }, [buildParentTreeNodes, dept.dept_id, dept.name, dept.parent_id, t, tree])

  const restoreBaseline = useCallback((b = baselineRef.current) => {
    if (!b) return
    setName(b.name)
    setAdminSelectValue(b.admins)
    adminSelectValueRef.current = b.admins
    setDefaultRoleIds(b.defaultRoleIds)
    setParentIdValue(b.parentId)
    setOrgLevelDraft(b.orgLevelDraft)
  }, [])

  const hasUnsavedSettingsChanges = useCallback(() => {
    const b = baselineRef.current
    if (!b) return false
    if (canEditName && name !== b.name) return true
    if (canEditParent && parentIdValue !== b.parentId) return true
    if (canEditOrgLevel && orgLevelDraft !== b.orgLevelDraft) return true
    if (
      !sameIdSet(
        adminSelectValue.map((o) => o.value),
        b.admins.map((o) => o.value)
      )
    ) return true
    if (!sameIdSet(defaultRoleIds, b.defaultRoleIds)) return true
    return false
  }, [
    adminSelectValue,
    canEditName,
    canEditOrgLevel,
    canEditParent,
    defaultRoleIds,
    name,
    orgLevelDraft,
    parentIdValue,
  ])

  const handleCancel = useCallback(() => {
    const b = baselineRef.current
    if (!b) return
    if (!hasUnsavedSettingsChanges()) {
      restoreBaseline(b)
      return
    }
    bsConfirm({
      title: t("prompt"),
      desc: t("department.confirmCancelSettings", { ns: "bs" }),
      onOk: (next) => {
        restoreBaseline(b)
        next()
      },
    })
  }, [hasUnsavedSettingsChanges, restoreBaseline, t])

  const handleGlobalSave = useCallback(async () => {
    if (!canEditPermissions) return
    if (canEditName && (!name || name.length < 2 || name.length > 50)) {
      toast({
        title: t("prompt"),
        description: t("bs:department.nameLength"),
        variant: "error",
      })
      return
    }
    setSaving(true)
    try {
      const body: {
        name?: string
        default_role_ids?: number[]
        admin_user_ids?: number[]
        apply_default_roles_to_existing_members?: boolean
      } = {}
      const baseline = baselineRef.current
      const nextName = name.trim()
      const nextAdminIds = adminSelectValue.map((o) => o.value)
      const nextDefaultRoleIds = defaultRoleIds.map(Number)
      if (canEditName && baseline && nextName !== baseline.name) {
        body.name = nextName
      }
      if (
        baseline &&
        !sameIdSet(
          nextAdminIds,
          baseline.admins.map((o) => o.value)
        )
      ) {
        body.admin_user_ids = nextAdminIds
      }
      if (baseline && !sameIdSet(nextDefaultRoleIds, baseline.defaultRoleIds)) {
        body.default_role_ids = nextDefaultRoleIds
      }
      if (applyDefaultRolesToExisting) {
        body.apply_default_roles_to_existing_members = true
      }
      const nextParentId = parentIdValue
      const parentChanged =
        canEditParent &&
        baseline &&
        nextParentId !== null &&
        nextParentId !== baseline.parentId
      const orgLevelChanged =
        canEditOrgLevel && !!baseline && orgLevelDraft !== baseline.orgLevelDraft

      if (!parentChanged && Object.keys(body).length === 0 && !orgLevelChanged) {
        return
      }

      if (parentChanged) {
        const moveRes = await captureAndAlertRequestErrorHoc(
          moveDepartmentApi(dept.dept_id, nextParentId)
        )
        if (moveRes === null || moveRes === false) return
      }
      if (Object.keys(body).length > 0) {
        const res = await captureAndAlertRequestErrorHoc(
          updateDepartmentApi(dept.dept_id, body)
        )
        if (res === null || res === false) return
      } else if (parentChanged && !orgLevelChanged) {
        // 仅移动父部门时无需再打 update。
      }

      // 组织层级走独立 API；与基础字段同一次「保存」提交，避免单独设公司按钮。
      if (orgLevelChanged) {
        if (orgLevelDraft === "company") {
          const labelRes = await captureAndAlertRequestErrorHoc(
            setDepartmentCompanyRootApi(dept.dept_id)
          )
          if (labelRes === null || labelRes === false) return
        } else if (baseline?.orgLevelDraft === "company") {
          const clearRes = await captureAndAlertRequestErrorHoc(
            clearDepartmentCompanyRootApi(dept.dept_id)
          )
          if (clearRes === null || clearRes === false) return
        }
        onOrgLevelChanged?.()
      }

      toast({
        title: t("prompt"),
        description: t("saved"),
        variant: "success",
      })
      setApplyDefaultRolesToExisting(false)
      const nextAdmins = await getDepartmentAdminsApi(dept.dept_id).catch(() => null)
      const adminOpts = Array.isArray(nextAdmins)
        ? adminsToOptions(nextAdmins)
        : adminSelectValue
      setAdminSelectValue(adminOpts)
      adminSelectValueRef.current = adminOpts
      baselineRef.current = {
        name: nextName,
        admins: adminOpts,
        defaultRoleIds: [...defaultRoleIds],
        parentId: nextParentId ?? baselineRef.current?.parentId ?? dept.parent_id ?? null,
        orgLevelDraft,
      }
      onChanged()
    } finally {
      setSaving(false)
    }
  }, [
    adminSelectValue,
    canEditName,
    canEditOrgLevel,
    canEditParent,
    canEditPermissions,
    applyDefaultRolesToExisting,
    defaultRoleIds,
    dept.dept_id,
    dept.parent_id,
    name,
    onChanged,
    onOrgLevelChanged,
    orgLevelDraft,
    parentIdValue,
    t,
  ])

  const handleDelete = useCallback(() => {
    bsConfirm({
      title: t("bs:department.delete"),
      desc: t("bs:department.confirmDelete"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(deleteDepartmentApi(dept.dept_id)).then((res) => {
          if (res !== false && res !== "canceled") {
            toast({
              title: t("prompt"),
              description: t("deleteSuccess"),
              variant: "success",
            })
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
        captureAndAlertRequestErrorHoc(purgeDepartmentApi(dept.dept_id)).then((res) => {
          if (res !== false && res !== "canceled") {
            toast({
              title: t("prompt"),
              description: t("deleteSuccess"),
              variant: "success",
            })
            onChanged(dept.dept_id)
          }
          next()
        })
      },
    })
  }, [dept.dept_id, onChanged, t])

  const handleRestore = useCallback(() => {
    bsConfirm({
      title: t("bs:department.restore"),
      desc: t("bs:department.confirmRestore"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(restoreDepartmentApi(dept.dept_id)).then((res) => {
          if (res !== false && res !== "canceled") {
            toast({
              title: t("prompt"),
              description: t("save") + t("success"),
              variant: "success",
            })
            onChanged()
          }
          next()
        })
      },
    })
  }, [dept.dept_id, onChanged, t])

  const findParentDisplay = (
    nodes: DepartmentTreeNode[],
    parentId: number | null
  ): string => {
    if (parentId === null) return "-"
    for (const n of nodes) {
      if (n.id === parentId) return n.name
      const found = findParentDisplay(n.children || [], parentId)
      if (found !== "-") return found
    }
    return "-"
  }

  return (
    <div className="max-w-3xl pb-8">
      {isArchived && (
        <div className="mb-4 rounded-md border border-orange-200 bg-orange-50 p-3 text-sm text-orange-800 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-200">
          {t("bs:department.archivedNotice")}
        </div>
      )}

      {loading && (
        <p className="mb-4 text-sm text-muted-foreground">{t("loading", { ns: "bs" })}</p>
      )}

      {/* 区块一：基础信息 */}
      <section className="space-y-4">
        <div>
          <h3 className="mb-2 text-base font-semibold tracking-tight text-foreground">
            {t("bs:department.sectionBasic")}
          </h3>
          <Separator />
        </div>
        <div className="space-y-1.5">
          <Label>{t("bs:department.name")}</Label>
          {isSynced || isArchived ? (
            <Input value={name} disabled className={FORM_CONTROL_WIDTH} />
          ) : (
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={50}
              className={FORM_CONTROL_WIDTH}
            />
          )}
        </div>
        {!isDefaultRootDept && (
          <div className="space-y-1.5">
            <Label>{t("bs:department.parentDept")}</Label>
            {canEditParent ? (
              <TreeDepartmentSelect
                nodes={parentTreeNodes}
                value={parentIdValue}
                onChange={(id) => setParentIdValue(id)}
                className={FORM_CONTROL_WIDTH}
                placeholder={t("bs:department.selectDept")}
                searchPlaceholder={t("bs:department.parentDept")}
                modal={false}
              />
            ) : (
              <Input
                value={findParentDisplay(tree, dept.parent_id)}
                disabled
                className={FORM_CONTROL_WIDTH}
              />
            )}
          </div>
        )}
      </section>

      {/* 区块：组织层级标签（不改拓扑/挂载；可编辑时经底部保存提交） */}
      {!isArchived && (
        <section className="mt-6 space-y-4">
          <div>
            <h3 className="mb-2 text-base font-semibold tracking-tight text-foreground">
              {t("bs:department.sectionOrgLevel")}
            </h3>
            <Separator />
          </div>
          <p className="max-w-xl text-sm text-muted-foreground">
            {t("bs:department.orgLevelHint")}
          </p>
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <Label>{t("bs:department.orgLevelLabel")}</Label>
              {orgLevelDisabledReason ? (
                <QuestionTooltip
                  content={t("bs:department.setCompanyRootDisabledUnderSubtree")}
                />
              ) : null}
            </div>
            {canEditOrgLevel ? (
              <div className={`flex items-center gap-2 ${FORM_CONTROL_WIDTH}`}>
                <Select
                  // 清除后 remount，避免 Radix 受控 value 从 company → 空时状态残留。
                  key={orgLevelDraft === "company" ? "company" : "unset"}
                  value={orgLevelDraft === "company" ? "company" : undefined}
                  onValueChange={(v) => {
                    if (v === "company") setOrgLevelDraft("company")
                  }}
                  disabled={saving}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder={t("bs:department.orgLevelUnset")} />
                  </SelectTrigger>
                  <SelectContent>
                    {/* 手动可选层级仅「公司」；部门/科室/班组由级联自动标注。 */}
                    <SelectItem value="company">
                      {t("bs:department.orgLevel.company")}
                    </SelectItem>
                  </SelectContent>
                </Select>
                {orgLevelDraft === "company" ? (
                  <Button
                    type="button"
                    variant="ghost"
                    className="shrink-0 px-2"
                    disabled={saving}
                    onClick={() => setOrgLevelDraft(ORG_LEVEL_UNSET)}
                  >
                    {t("bs:department.orgLevelClear")}
                  </Button>
                ) : null}
              </div>
            ) : (
              <Input
                value={
                  orgLevel
                    ? t(`bs:department.orgLevel.${orgLevel}`)
                    : t("bs:department.orgLevelUnset")
                }
                disabled
                className={FORM_CONTROL_WIDTH}
              />
            )}
          </div>
        </section>
      )}

      {/* 区块二：权限与角色 */}
      {!isArchived && (
        <section className="mt-6 space-y-4">
          <div>
            <h3 className="mb-2 text-base font-semibold tracking-tight text-foreground">
              {t("bs:department.sectionPermissions")}
            </h3>
            <Separator />
          </div>
          <div className="space-y-1.5">
            <Label>{t("bs:department.admins")}</Label>
            <DepartmentUsersSelect
              multiple
              disabled={!canEditPermissions}
              value={adminSelectValue}
              onChange={(vals) => {
                const v = (vals as DepartmentUserOption[]) || []
                setAdminSelectValue(v)
                adminSelectValueRef.current = v
              }}
              placeholder={t("bs:department.adminSelectPlaceholder")}
              searchPlaceholder={t("bs:department.searchUsersPlaceholder")}
              className={FORM_CONTROL_WIDTH}
              // Tenant-root depts: admin assignment writes the FGA
              // ``admin tenant:X`` tuple, so we constrain the picker to the
              // dept's own subtree. Plain depts keep the full org tree.
              rootDeptId={dept.is_tenant_root ? dept.id : undefined}
              emptyMessage={
                dept.is_tenant_root
                  ? t("bs:tenant.initialAdminEmptySubtree", {
                      defaultValue:
                        "该部门子树暂无成员，请先把目标管理员加入此部门后再挂载",
                    })
                  : undefined
              }
            />
            {dept.is_tenant_root ? (
              <p className="mt-1 max-w-md text-xs leading-snug text-gray-500 dark:text-gray-400">
                {t("bs:tenant.initialAdminSubtreeHint", {
                  defaultValue: "管理员必须来自该部门子树，不能选取子树外用户。",
                })}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label>{t("bs:department.defaultRoles")}</Label>
            <MultiSelect
              multiple
              value={defaultRoleIds}
              options={assignableRoles}
              placeholder={t("bs:department.selectRoles")}
              onChange={(vals) => setDefaultRoleIds(vals as string[])}
              disabled={!canEditPermissions}
              className={FORM_CONTROL_WIDTH}
            />
            <label className="mt-2 flex max-w-md cursor-pointer items-start gap-2 text-sm leading-snug">
              <Checkbox
                className="mt-0.5"
                checked={applyDefaultRolesToExisting}
                disabled={!canEditPermissions}
                onCheckedChange={(v) => setApplyDefaultRolesToExisting(Boolean(v))}
              />
              <span className="flex flex-1 flex-wrap items-center gap-1.5 text-foreground">
                {t("bs:department.applyDefaultRolesToExisting")}
                <span
                  className="inline-flex shrink-0"
                  onClick={(e) => e.preventDefault()}
                  onPointerDown={(e) => e.stopPropagation()}
                >
                  <QuestionTooltip
                    className="text-muted-foreground hover:text-foreground"
                    content={t("bs:department.applyDefaultRolesToExistingTooltip")}
                  />
                </span>
              </span>
            </label>
            <p className="mt-1 max-w-md text-xs leading-snug text-gray-500 dark:text-gray-400">
              {t("bs:department.defaultRolesHint")}
            </p>
          </div>
        </section>
      )}

      {/* 已归档：还原 / 永久删除 */}
      {isArchived && (
        <div className="mt-5 border-t pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={handleRestore}>
              {t("bs:department.restore")}
            </Button>
            {!isGuestDepartmentDeptId(dept.dept_id) ? (
              <Button variant="destructive" onClick={handlePurge}>
                {t("bs:department.permanentDelete")}
              </Button>
            ) : null}
          </div>
        </div>
      )}

      {/* 全局保存 + 删除部门 */}
      {!isArchived && (
        <div className="mt-5 border-t pt-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {canEditPermissions && (
                <Button type="button" onClick={() => void handleGlobalSave()} disabled={saving}>
                  {t("save")}
                </Button>
              )}
            </div>
            <div className="min-w-[1rem] flex-1" />
            {onMarkAsTenant && !isDefaultRootDept && !dept.is_tenant_root && (
              <Button
                variant="outline"
                onClick={() => onMarkAsTenant(dept.id, dept.name)}
                className="shrink-0"
              >
                <Building2 className="mr-1.5 h-4 w-4" />
                {t("bs:tenant.markAsTenant", { defaultValue: "标记为子租户" })}
              </Button>
            )}
            {onMarkAsTenant && !isDefaultRootDept && dept.is_tenant_root && (
              <Button
                variant="outline"
                onClick={() => {
                  bsConfirm({
                    title: t("bs:tenant.unmountTitle", { defaultValue: "取消挂载子租户" }),
                    desc: t("bs:tenant.unmountConfirm", {
                      defaultValue:
                        "解除挂载后，该子租户名下的所有资源（知识库、应用、会话等）将自动迁移到集团总部（Root），子租户本身归档保留供审计。子租户成员将作为总部成员继续使用，业务不中断。是否继续？",
                    }),
                    okTxt: t("bs:tenant.unmountOk", { defaultValue: "确认取消挂载" }),
                    onOk(next) {
                      captureAndAlertRequestErrorHoc(
                        unmountTenantApi(dept.id)
                      ).then((res) => {
                        if (res) {
                          toast({
                            title: t("bs:tenant.unmountSuccess", {
                              defaultValue: "已取消挂载",
                            }),
                            variant: "success",
                          })
                          onChanged()
                        }
                        next()
                      })
                    },
                  })
                }}
                className="shrink-0"
              >
                <Building2 className="mr-1.5 h-4 w-4" />
                {t("bs:tenant.unmount", { defaultValue: "取消挂载" })}
              </Button>
            )}
            {!isSynced &&
              dept.parent_id !== null &&
              !isGuestDepartmentDeptId(dept.dept_id) && (
              <Button variant="destructive" onClick={handleDelete} className="shrink-0">
                {t("bs:department.delete")}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
