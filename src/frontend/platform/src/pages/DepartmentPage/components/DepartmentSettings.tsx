import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Input } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import MultiSelect from "@/components/bs-ui/select/multi"
import { Separator } from "@/components/bs-ui/separator"
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
  updateDepartmentApi,
} from "@/controllers/API/department"
import { isSyncedSource } from "@/pages/DepartmentPage/constants/syncReadonly"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import type { DepartmentAdmin, DepartmentTreeNode } from "@/types/api/department"
import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

interface DepartmentSettingsProps {
  dept: DepartmentTreeNode
  tree: DepartmentTreeNode[]
  onChanged: (removedDeptId?: string) => void
}

function adminsToOptions(admins: DepartmentAdmin[]): DepartmentUserOption[] {
  return admins.map((a) => ({ value: Number(a.user_id), label: a.user_name }))
}

/** 企业级表单：统一控件最大宽度，右侧对齐 */
const FORM_CONTROL_WIDTH = "w-full max-w-md"

export function DepartmentSettings({ dept, tree, onChanged }: DepartmentSettingsProps) {
  const { t } = useTranslation()
  const [name, setName] = useState(dept.name)
  const [adminSelectValue, setAdminSelectValue] = useState<DepartmentUserOption[]>([])
  const [defaultRoleIds, setDefaultRoleIds] = useState<string[]>([])
  const [assignableRoles, setAssignableRoles] = useState<{ value: string; label: string }[]>([])
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [parentIdValue, setParentIdValue] = useState<number | null>(dept.parent_id ?? null)
  const [parentTreeNodes, setParentTreeNodes] = useState<DepartmentTreeNode[]>([])

  const adminSelectValueRef = useRef<DepartmentUserOption[]>([])

  const isSynced = isSyncedSource(dept.source)
  const isArchived = dept.status === "archived"
  const isAbsoluteRootDept = dept.parent_id === null || Number(dept.parent_id) === 0
  // 对部门管理员场景：当前可见树的顶层节点也视为“根节点”（即便全局树里它还有父节点）
  const isVisibleRootDept = tree.some((n) => n.id === dept.id)
  const isRootDept = isAbsoluteRootDept || isVisibleRootDept
  /** 仅部门名称对第三方同步部门只读；管理员与默认角色仍可保存 */
  const canEditName = !isArchived && !isSynced
  const canEditPermissions = !isArchived
  const canEditParent = !isArchived && !isSynced && !isRootDept

  /** 最近一次从服务端加载成功的快照，用于「取消」还原 */
  const baselineRef = useRef<{
    name: string
    admins: DepartmentUserOption[]
    defaultRoleIds: string[]
    parentId: number | null
  } | null>(null)

  useEffect(() => {
    adminSelectValueRef.current = adminSelectValue
  }, [adminSelectValue])

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
        setAssignableRoles(
          (rolesRes || []).map((r) => ({ value: String(r.id), label: r.role_name }))
        )
        baselineRef.current = {
          name: detailRes?.name ?? dept.name,
          admins: adminOpts,
          defaultRoleIds: dr,
          parentId: pid,
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
  }, [buildParentTreeNodes, dept.dept_id, dept.name, dept.parent_id, t, tree])

  const handleCancel = useCallback(() => {
    const b = baselineRef.current
    if (!b) return
    setName(b.name)
    setAdminSelectValue(b.admins)
    adminSelectValueRef.current = b.admins
    setDefaultRoleIds(b.defaultRoleIds)
    setParentIdValue(b.parentId)
  }, [])

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
        default_role_ids: number[]
        admin_user_ids: number[]
      } = {
        default_role_ids: defaultRoleIds.map(Number),
        admin_user_ids: adminSelectValue.map((o) => o.value),
      }
      if (canEditName) body.name = name.trim()
      const nextParentId = parentIdValue
      const parentChanged =
        canEditParent &&
        baselineRef.current &&
        nextParentId !== null &&
        nextParentId !== baselineRef.current.parentId

      if (parentChanged) {
        const moveRes = await captureAndAlertRequestErrorHoc(
          moveDepartmentApi(dept.dept_id, nextParentId)
        )
        if (moveRes === null || moveRes === false) return
      }
      const res = await captureAndAlertRequestErrorHoc(
        updateDepartmentApi(dept.dept_id, body)
      )
      if (res === null || res === false) return
      toast({
        title: t("prompt"),
        description: t("saved"),
        variant: "success",
      })
      const nextAdmins = await getDepartmentAdminsApi(dept.dept_id).catch(() => null)
      const adminOpts = Array.isArray(nextAdmins)
        ? adminsToOptions(nextAdmins)
        : adminSelectValue
      setAdminSelectValue(adminOpts)
      adminSelectValueRef.current = adminOpts
      baselineRef.current = {
        name: name.trim(),
        admins: adminOpts,
        defaultRoleIds: [...defaultRoleIds],
        parentId: nextParentId ?? baselineRef.current?.parentId ?? dept.parent_id ?? null,
      }
      onChanged()
    } finally {
      setSaving(false)
    }
  }, [
    adminSelectValue,
    canEditName,
    canEditParent,
    canEditPermissions,
    defaultRoleIds,
    dept.dept_id,
    dept.parent_id,
    name,
    onChanged,
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
            <div>
              <Input value={name} disabled className={FORM_CONTROL_WIDTH} />
              <p className="mt-1 text-xs text-muted-foreground">
                {t("bs:department.readonlyField")}
              </p>
            </div>
          ) : (
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={50}
              className={FORM_CONTROL_WIDTH}
            />
          )}
        </div>
        {!isRootDept && (
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
            />
            <p className="mt-1 max-w-md text-xs leading-snug text-gray-500 dark:text-gray-400">
              {t("bs:department.adminsHint")}
            </p>
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
            <Button variant="destructive" onClick={handlePurge}>
              {t("bs:department.permanentDelete")}
            </Button>
          </div>
        </div>
      )}

      {/* 全局保存 / 取消 + 删除部门 */}
      {!isArchived && (
        <div className="mt-5 border-t pt-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {canEditPermissions && (
                <>
                  <Button type="button" onClick={() => void handleGlobalSave()} disabled={saving}>
                    {t("save")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handleCancel}
                    disabled={saving}
                  >
                    {t("bs:cancel")}
                  </Button>
                </>
              )}
            </div>
            <div className="min-w-[1rem] flex-1" />
            {!isSynced && dept.parent_id !== null && (
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
