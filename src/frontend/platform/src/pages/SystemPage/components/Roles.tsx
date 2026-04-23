import { PlusIcon } from "@/components/bs-icons/plus"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import { Switch } from "@/components/bs-ui/switch"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import { Input, SearchInput } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import {
  ColumnResizeHandle,
  useResizableColumns,
} from "@/components/bs-ui/table/useResizableColumns"
import { cname } from "@/components/bs-ui/utils"
import { userContext } from "@/contexts/userContext"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import {
  createRoleV2Api,
  deleteRoleV2Api,
  getRoleMenuV2Api,
  getRolesPageApi,
  updateRoleV2Api,
} from "@/controllers/API/user"
import { message } from "@/components/bs-ui/toast/use-toast"
import { TreeDepartmentSelect, getDepartmentDisplayPath } from "@/components/bs-comp/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentTreeNode } from "@/types/api/department"
import { ROLE } from "@/types/api/user"
import { useContext, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

const WORKBENCH_PARENT_ID = "workstation"
const ADMIN_PARENT_ID = "admin"
const WORKBENCH_CHILD_MENUS = ["subscription", "knowledge_space"] as const
const ADMIN_CHILD_MENUS = [
  "board",
  "model",
  "log",
  "knowledge",
  "create_knowledge",
  "build",
  "create_app",
  "evaluation",
  "mark_task",
] as const
/**
 * 某些子菜单依赖另一个子菜单（父项关闭则隐藏、且会级联移除）。
 * `create_app` 依赖 `build`；"新建知识库"依赖 `knowledge`（PRD 3.3.3）。
 */
const ADMIN_CHILD_DEPENDENTS: Record<string, readonly string[]> = {
  build: ["create_app"],
  knowledge: ["create_knowledge"],
}
const DEFAULT_ENABLED_MENU_IDS = [
  WORKBENCH_PARENT_ID,
  ADMIN_PARENT_ID,
  "knowledge_space",
  "knowledge",
  "build",
] as const

export default function Roles() {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  const isPlatformAdmin = user?.role === "admin"

  const [roles, setRoles] = useState<ROLE[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState("")
  const [deptTree, setDeptTree] = useState<DepartmentTreeNode[]>([])
  const [editOpen, setEditOpen] = useState(false)
  const [activeRole, setActiveRole] = useState<ROLE | null>(null)
  const [roleName, setRoleName] = useState("")
  const [departmentId, setDepartmentId] = useState<string>("none")
  const [quotaFileUnlimited, setQuotaFileUnlimited] = useState(false)
  const [quotaFileGb, setQuotaFileGb] = useState("500")
  const [quotaChannelUnlimited, setQuotaChannelUnlimited] = useState(false)
  const [quotaChannelCount, setQuotaChannelCount] = useState("10")
  const [menuIds, setMenuIds] = useState<string[]>([])
  const [isMenuLoading, setIsMenuLoading] = useState(false)
  const [menuLoadFailed, setMenuLoadFailed] = useState(false)
  const [initialEditSnapshot, setInitialEditSnapshot] = useState("")
  const [isSaving, setIsSaving] = useState(false)

  const WORKBENCH_MENU_OPTIONS = useMemo(
    () => [
      { id: "subscription", label: t("menu.workbench1") },
      { id: "knowledge_space", label: t("menu.workbench2") },
    ],
    [t]
  )

  const ADMIN_MENU_OPTIONS = useMemo(
    () => [
      { id: "board", label: t("menu.board") },
      { id: "model", label: t("menu.models") },
      { id: "log", label: t("menu.log") },
      { id: "knowledge", label: t("menu.knowledge") },
      { id: "create_knowledge", label: t("menu.createKnowledge"), parentMenuId: "knowledge" as const },
      { id: "build", label: t("menu.skills") },
      // `create_app` 依赖 `build`：只有当构建开启时渲染，关闭构建时级联移除。
      { id: "create_app", label: t("menu.createApp"), parentMenuId: "build" as const },
      { id: "evaluation", label: t("menu.evaluation") },
      { id: "mark_task", label: t("menu.annotation") },
    ],
    [t]
  )

  const defaultMenuIds = useMemo(() => [...DEFAULT_ENABLED_MENU_IDS], [])

  const roleTableCols = useMemo(
    () => [
      { defaultWidth: 180, minWidth: 120 },
      { defaultWidth: 280, minWidth: 200 },
      { defaultWidth: 100, minWidth: 80 },
      { defaultWidth: 140, minWidth: 100 },
      { defaultWidth: 170, minWidth: 140 },
      { defaultWidth: 170, minWidth: 140 },
      { defaultWidth: 168, minWidth: 120 },
    ],
    []
  )
  const rc = useResizableColumns(roleTableCols)
  const roleLastCol = roleTableCols.length - 1

  const buildEditSnapshot = (
    roleNameVal: string,
    departmentIdVal: string,
    quotaFileUnlimitedVal: boolean,
    quotaFileGbVal: string,
    quotaChannelUnlimitedVal: boolean,
    quotaChannelCountVal: string,
    menuIdsVal: string[]
  ) => JSON.stringify({
    roleNameVal,
    departmentIdVal,
    quotaFileUnlimitedVal,
    quotaFileGbVal,
    quotaChannelUnlimitedVal,
    quotaChannelCountVal,
    menuIds: [...menuIdsVal].sort(),
  })

  const loadDepartments = async () => {
    const res = await captureAndAlertRequestErrorHoc(getDepartmentTreeApi())
    if (res) setDeptTree(res)
  }

  const loadRoles = async (nextPage = page, nextKeyword = keyword) => {
    const res = await captureAndAlertRequestErrorHoc(
      getRolesPageApi({ page: nextPage, limit: 20, keyword: nextKeyword || undefined })
    )
    if (res) {
      setRoles(res.data || [])
      setTotal(res.total || 0)
    }
  }

  useEffect(() => {
    loadDepartments()
  }, [])

  useEffect(() => {
    loadRoles(1, keyword)
    setPage(1)
  }, [keyword])

  const fmtTime = (v?: string) => (v ? String(v).replace("T", " ").slice(0, 19) : "-")

  const openCreate = () => {
    const nextDepartmentId = isPlatformAdmin ? "none" : deptTree[0] ? String(deptTree[0].id) : "none"
    const nextMenuIds = [...defaultMenuIds]
    setActiveRole(null)
    setRoleName("")
    setDepartmentId(nextDepartmentId)
    setQuotaFileUnlimited(false)
    setQuotaFileGb("500")
    setQuotaChannelUnlimited(false)
    setQuotaChannelCount("10")
    setMenuIds(nextMenuIds)
    setIsMenuLoading(false)
    setMenuLoadFailed(false)
    setInitialEditSnapshot(
      buildEditSnapshot("", nextDepartmentId, false, "500", false, "10", nextMenuIds)
    )
    setEditOpen(true)
  }

  const loadRoleMenus = async (
    role: ROLE,
    fileLimit: number,
    channelLimit: number
  ) => {
    setIsMenuLoading(true)
    setMenuLoadFailed(false)
    const menuRes = await captureAndAlertRequestErrorHoc(getRoleMenuV2Api(role.id))
    if (menuRes === false || !Array.isArray(menuRes)) {
      setMenuLoadFailed(true)
      setInitialEditSnapshot("")
      setIsMenuLoading(false)
      return
    }
    let ids = [...menuRes].filter((id) => id !== "system_config")
    // 依赖约束：若父项未启用则剔除依赖项（例如 create_app 依赖 build）。
    Object.entries(ADMIN_CHILD_DEPENDENTS).forEach(([parent, deps]) => {
      if (!ids.includes(parent)) ids = ids.filter((id) => !deps.includes(id))
    })
    if (ids.some((id) => (ADMIN_CHILD_MENUS as readonly string[]).includes(id)) && !ids.includes(ADMIN_PARENT_ID)) {
      ids = [...ids, ADMIN_PARENT_ID]
    }
    if (
      ids.some((id) => (WORKBENCH_CHILD_MENUS as readonly string[]).includes(id)) &&
      !ids.includes(WORKBENCH_PARENT_ID)
    ) {
      ids = [...ids, WORKBENCH_PARENT_ID]
    }
    setMenuIds(ids)
    setInitialEditSnapshot(
      buildEditSnapshot(
        role.role_name || "",
        role.department_id ? String(role.department_id) : "none",
        fileLimit === -1,
        fileLimit > 0 ? String(fileLimit) : "500",
        channelLimit === -1,
        channelLimit >= 0 ? String(channelLimit) : "10",
        ids
      )
    )
    setIsMenuLoading(false)
  }

  const openEdit = async (role: ROLE) => {
    const qc = role.quota_config || {}
    setActiveRole(role)
    setRoleName(role.role_name || "")
    setDepartmentId(role.department_id ? String(role.department_id) : "none")
    const fileLimit = Number(qc.knowledge_space_file ?? -1)
    const channelLimit = Number(qc.channel ?? 10)
    setQuotaFileUnlimited(fileLimit === -1)
    setQuotaFileGb(fileLimit > 0 ? String(fileLimit) : "500")
    setQuotaChannelUnlimited(channelLimit === -1)
    setQuotaChannelCount(channelLimit >= 0 ? String(channelLimit) : "10")
    setMenuIds([])
    setMenuLoadFailed(false)
    setEditOpen(true)
    await loadRoleMenus(role, fileLimit, channelLimit)
  }

  const buildQuotaConfig = (): Record<string, number> => {
    const base: Record<string, number> = activeRole?.quota_config
      ? { ...(activeRole.quota_config as Record<string, number>) }
      : {}
    base.knowledge_space_file = quotaFileUnlimited ? -1 : Math.max(0, Number(quotaFileGb || 0))
    base.channel = quotaChannelUnlimited ? -1 : Math.max(0, Number(quotaChannelCount || 0))
    return base
  }

  const submitRole = async () => {
    if (isSaving || !roleName.trim() || isMenuLoading || menuLoadFailed) return
    setIsSaving(true)
    const quota_config = buildQuotaConfig()
    // 保存前清理依赖：父项未开则不应持久化依赖项（例如 build 关闭时移除 create_app）。
    const sanitizedMenuIds = menuIds.filter((id) => {
      const parent = Object.entries(ADMIN_CHILD_DEPENDENTS).find(([, deps]) =>
        (deps as readonly string[]).includes(id),
      )?.[0]
      return !parent || menuIds.includes(parent)
    })
    const payload = {
      role_name: roleName.trim(),
      department_id: departmentId === "none" ? null : Number(departmentId),
      quota_config,
      remark: "PRD 2.5 role",
      menu_ids: sanitizedMenuIds,
    }
    try {
      if (!activeRole) {
        const created = await captureAndAlertRequestErrorHoc(createRoleV2Api(payload))
        if (created === null || created === false) return
      } else {
        const updated = await captureAndAlertRequestErrorHoc(updateRoleV2Api(activeRole.id, payload))
        if (updated === null || updated === false) return
      }

      message({ variant: "success", description: t("saved") })
      setEditOpen(false)
      await loadRoles()
    } finally {
      setIsSaving(false)
    }
  }

  const onDelete = (item: ROLE) => {
    const n = item.user_count ?? 0
    const desc =
      n > 0 ? (
        <div className="space-y-2 text-left text-sm">
          <p>
            {t("system.confirmText")}「{item.role_name}」？
          </p>
          <p className="text-muted-foreground">
            {t("system.roleDeleteRevokeWarning", { count: n })}
          </p>
        </div>
      ) : (
        `${t("system.confirmText")}「${item.role_name}」？`
      )
    bsConfirm({
      title: t("prompt"),
      desc,
      okTxt: t("delete"),
      onOk: async (next) => {
        try {
          const res = await captureAndAlertRequestErrorHoc(deleteRoleV2Api(item.id))
          if (res === false) return
          await loadRoles()
          message({ variant: "success", description: t("deleteSuccess") })
        } finally {
          next()
        }
      },
    })
  }

  const isMenuEnabled = (id: string) => menuIds.includes(id)
  const isGroupAllEnabled = (children: readonly string[]) => children.every((id) => isMenuEnabled(id))

  const toggleMenuGroup = (parentId: string, children: readonly string[], checked: boolean) => {
    setMenuIds((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(parentId)
        children.forEach((id) => next.add(id))
      } else {
        next.delete(parentId)
        children.forEach((id) => next.delete(id))
      }
      return Array.from(next)
    })
  }

  const toggleMenuItem = (parentId: string, children: readonly string[], id: string, checked: boolean) => {
    setMenuIds((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(id)
        next.add(parentId)
      } else {
        next.delete(id)
        // 关闭父级子菜单时，级联移除其依赖的子菜单（例如 build -> create_app）
        const dependents = ADMIN_CHILD_DEPENDENTS[id] || []
        dependents.forEach((dep) => next.delete(dep))
        const hasAnyChild = children.some((child) => child !== id && next.has(child))
        if (!hasAnyChild) next.delete(parentId)
      }
      return Array.from(next)
    })
  }

  const scopeLabel = (el: ROLE) => {
    // 作用域以 department_id 为准；全路径优先用后端按 path 解析的字段（不受部门树裁剪影响）
    if (!el.department_id) return t("system.scopeGlobal")
    const fromApi = (el.department_scope_path || "").trim()
    if (fromApi) return fromApi
    return getDepartmentDisplayPath(deptTree, el.department_id) || el.department_name || "-"
  }

  const creatorLabel = (el: ROLE) => {
    return el.creator_name?.trim() || "-"
  }

  const hasUnsavedEditChanges = useMemo(() => {
    if (!editOpen || !initialEditSnapshot) return false
    const current = buildEditSnapshot(
      roleName,
      departmentId,
      quotaFileUnlimited,
      quotaFileGb,
      quotaChannelUnlimited,
      quotaChannelCount,
      menuIds
    )
    return current !== initialEditSnapshot
  }, [
    editOpen,
    initialEditSnapshot,
    roleName,
    departmentId,
    quotaFileUnlimited,
    quotaFileGb,
    quotaChannelUnlimited,
    quotaChannelCount,
    menuIds,
  ])

  const requestCloseEditDialog = () => {
    if (!hasUnsavedEditChanges) {
      setEditOpen(false)
      return
    }
    bsConfirm({
      title: t("prompt"),
      desc: t("unsavedChangesConfirmation"),
      okTxt: t("leave"),
      canelTxt: t("cancel"),
      onOk: (next) => {
        setEditOpen(false)
        next()
      },
    })
  }

  return (
    <div className="relative">
      <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10 pt-2">
        <div className="mb-3 flex items-center justify-between">
          <div className="w-[220px]">
            <SearchInput
              placeholder={t("system.roleSearchPlaceholder")}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </div>
          <Button className="flex justify-around" onClick={openCreate}>
            <PlusIcon className="text-primary" />
            <span className="mx-4 text-[#fff]">{t("create")}</span>
          </Button>
        </div>
        <Table
          noScroll
          className="mb-6 !w-auto min-w-full"
          style={{ tableLayout: "fixed", width: rc.totalWidth }}
        >
          <TableHeader>
            <TableRow>
              <TableHead {...rc.getThProps(0)}>
                {t("system.roleName")}
                <ColumnResizeHandle
                  columnIndex={0}
                  lastColumn={0 === roleLastCol}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(1)}>
                {t("system.roleScope")}
                <ColumnResizeHandle
                  columnIndex={1}
                  lastColumn={1 === roleLastCol}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(2)}>
                {t("system.userCount")}
                <ColumnResizeHandle
                  columnIndex={2}
                  lastColumn={2 === roleLastCol}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(3)}>
                {t("system.creator")}
                <ColumnResizeHandle
                  columnIndex={3}
                  lastColumn={3 === roleLastCol}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(4)}>
                {t("createTime")}
                <ColumnResizeHandle
                  columnIndex={4}
                  lastColumn={4 === roleLastCol}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(5)}>
                {t("system.changeTime")}
                <ColumnResizeHandle
                  columnIndex={5}
                  lastColumn={5 === roleLastCol}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead
                style={rc.getThProps(6).style}
                className={cname(rc.getThProps(6).className, "text-right")}
              >
                {t("operations")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {roles.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-gray-400">
                  {t("build.empty")}
                </TableCell>
              </TableRow>
            ) : (
              roles.map((el) => (
                <TableRow key={el.id}>
                  <TableCell {...rc.getTdProps(0)} className="font-medium">
                    {el.role_name}
                  </TableCell>
                  <TableCell
                    {...rc.getTdProps(1)}
                    className="whitespace-normal break-words text-left"
                  >
                    {scopeLabel(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(2)}>{el.user_count ?? "-"}</TableCell>
                  <TableCell {...rc.getTdProps(3)} className="text-sm text-muted-foreground">
                    {creatorLabel(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(4)}>{fmtTime(el.create_time)}</TableCell>
                  <TableCell {...rc.getTdProps(5)}>{fmtTime(el.update_time)}</TableCell>
                  <TableCell {...rc.getTdProps(6)} className="text-right">
                    {el.is_readonly ? (
                      <span className="text-sm text-muted-foreground">&mdash;</span>
                    ) : (
                      <>
                        <Button
                          variant="link"
                          className="px-0 pl-4"
                          onClick={() => openEdit(el)}
                        >
                          {t("edit")}
                        </Button>
                        <Button
                          variant="link"
                          disabled={[1, 2].includes(el.id)}
                          className="px-0 pl-4 text-red-500"
                          onClick={() => onDelete(el)}
                        >
                          {t("delete")}
                        </Button>
                      </>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        <AutoPagination
          className="m-0 w-auto justify-end"
          page={page}
          pageSize={20}
          total={total}
          showTotal={true}
          onChange={(p) => {
            setPage(p)
            loadRoles(p, keyword)
          }}
        />
      </div>

      <Dialog
        open={editOpen}
        onOpenChange={(open) => {
          if (open) {
            setEditOpen(true)
          } else {
            requestCloseEditDialog()
          }
        }}
      >
        <DialogContent className="flex max-h-[85vh] max-w-2xl flex-col sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{activeRole ? t("system.roleEditTitle") : t("system.roleCreateTitle")}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            <p className="text-xs text-muted-foreground">{t("system.roleFormIntro")}</p>

            <div>
              <Label>{t("system.roleName")}</Label>
              <Input value={roleName} onChange={(e) => setRoleName(e.target.value)} className="mt-1" maxLength={128} />
            </div>

            <div>
              <Label>{t("system.roleScope")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("system.roleScopeHint")}</p>
              <TreeDepartmentSelect
                modal={false}
                className="mt-1"
                nodes={deptTree}
                value={departmentId === "none" ? null : Number(departmentId)}
                onChange={(id) => setDepartmentId(id == null ? "none" : String(id))}
                allowNone={isPlatformAdmin}
                noneLabel={t("system.scopeGlobalRole")}
                placeholder={t("system.treeDepartmentSelectPlaceholder")}
                emptyText={t("system.treeDepartmentSelectEmpty")}
              />
            </div>

            <div className="rounded-md border p-3">
              <Label>{t("system.knowledgeSpaceFileUploadLimit")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("system.knowledgeSpaceFileLimitDesc")}</p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Checkbox
                  checked={quotaFileUnlimited}
                  onCheckedChange={(v) => setQuotaFileUnlimited(Boolean(v))}
                />
                <span className="text-sm">{t("system.unlimited")}</span>
                {!quotaFileUnlimited && (
                  <>
                    <Input
                      type="number"
                      min={0}
                      value={quotaFileGb}
                      onChange={(e) => setQuotaFileGb(e.target.value)}
                      className="w-[120px]"
                    />
                    <span className="text-sm">GB</span>
                  </>
                )}
              </div>
            </div>

            <div className="rounded-md border p-3">
              <Label>{t("system.channelQuotaLimit")}</Label>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Checkbox
                  checked={quotaChannelUnlimited}
                  onCheckedChange={(v) => setQuotaChannelUnlimited(Boolean(v))}
                />
                <span className="text-sm">{t("system.unlimited")}</span>
                {!quotaChannelUnlimited && (
                  <Input
                    type="number"
                    min={0}
                    value={quotaChannelCount}
                    onChange={(e) => setQuotaChannelCount(e.target.value)}
                    className="w-[120px]"
                  />
                )}
              </div>
            </div>

            <div className="rounded-md border p-3">
              <Label>{t("system.menuPermissionSection")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("system.menuPermissionHint")}</p>
              {isMenuLoading && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("system.roleMenuLoading")}
                </p>
              )}
              {menuLoadFailed && activeRole && (
                <div className="mt-2 flex items-center gap-3 text-xs text-destructive">
                  <span>{t("system.roleMenuLoadFailed")}</span>
                  <Button
                    type="button"
                    variant="link"
                    className="h-auto p-0 text-xs"
                    onClick={() => {
                      const qc = activeRole.quota_config || {}
                      const fileLimit = Number(qc.knowledge_space_file ?? -1)
                      const channelLimit = Number(qc.channel ?? 10)
                      void loadRoleMenus(activeRole, fileLimit, channelLimit)
                    }}
                  >
                    {t("retry")}
                  </Button>
                </div>
              )}
              <div className="mt-3 space-y-4">
                <div className="rounded-md border bg-muted/20 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-xs font-medium text-muted-foreground">{t("system.workbenchMenuAuthorization")}</div>
                    <div className="inline-flex items-center gap-2 text-xs">
                      <Button
                        type="button"
                        variant="link"
                        className="h-auto p-0"
                        onClick={() => toggleMenuGroup(WORKBENCH_PARENT_ID, WORKBENCH_CHILD_MENUS, true)}
                        disabled={isGroupAllEnabled(WORKBENCH_CHILD_MENUS)}
                      >
                        {t("system.menuEnableAll")}
                      </Button>
                      <span className="text-muted-foreground">/</span>
                      <Button
                        type="button"
                        variant="link"
                        className="h-auto p-0"
                        onClick={() => toggleMenuGroup(WORKBENCH_PARENT_ID, WORKBENCH_CHILD_MENUS, false)}
                        disabled={!isMenuEnabled(WORKBENCH_PARENT_ID)}
                      >
                        {t("system.menuDisableAll")}
                      </Button>
                    </div>
                  </div>
                  <label
                    className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-background px-2 py-1 text-base font-semibold"
                    onClick={() =>
                      toggleMenuGroup(
                        WORKBENCH_PARENT_ID,
                        WORKBENCH_CHILD_MENUS,
                        !isMenuEnabled(WORKBENCH_PARENT_ID)
                      )
                    }
                  >
                    <Switch
                      checked={isMenuEnabled(WORKBENCH_PARENT_ID)}
                      onCheckedChange={(checked) =>
                        toggleMenuGroup(WORKBENCH_PARENT_ID, WORKBENCH_CHILD_MENUS, checked)
                      }
                      onClick={(e) => e.stopPropagation()}
                    />
                    <span>{t("menu.workspace")}</span>
                  </label>
                  <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
                    {WORKBENCH_MENU_OPTIONS.map((m) => (
                      <label
                        key={m.id}
                        className={`inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-background px-2 py-1.5 text-sm ${
                          !isMenuEnabled(WORKBENCH_PARENT_ID) ? "opacity-50" : ""
                        }`}
                        onClick={() =>
                          isMenuEnabled(WORKBENCH_PARENT_ID) &&
                          toggleMenuItem(
                            WORKBENCH_PARENT_ID,
                            WORKBENCH_CHILD_MENUS,
                            m.id,
                            !isMenuEnabled(m.id)
                          )
                        }
                      >
                        <Switch
                          checked={isMenuEnabled(m.id)}
                          disabled={!isMenuEnabled(WORKBENCH_PARENT_ID)}
                          onCheckedChange={(checked) =>
                            toggleMenuItem(WORKBENCH_PARENT_ID, WORKBENCH_CHILD_MENUS, m.id, checked)
                          }
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span>{m.label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="rounded-md border bg-muted/20 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-xs font-medium text-muted-foreground">{t("system.adminMenuAuthorization")}</div>
                    <div className="inline-flex items-center gap-2 text-xs">
                      <Button
                        type="button"
                        variant="link"
                        className="h-auto p-0"
                        onClick={() => toggleMenuGroup(ADMIN_PARENT_ID, ADMIN_CHILD_MENUS, true)}
                        disabled={isGroupAllEnabled(ADMIN_CHILD_MENUS)}
                      >
                        {t("system.menuEnableAll")}
                      </Button>
                      <span className="text-muted-foreground">/</span>
                      <Button
                        type="button"
                        variant="link"
                        className="h-auto p-0"
                        onClick={() => toggleMenuGroup(ADMIN_PARENT_ID, ADMIN_CHILD_MENUS, false)}
                        disabled={!isMenuEnabled(ADMIN_PARENT_ID)}
                      >
                        {t("system.menuDisableAll")}
                      </Button>
                    </div>
                  </div>
                  <label
                    className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-background px-2 py-1 text-base font-semibold"
                    onClick={() =>
                      toggleMenuGroup(ADMIN_PARENT_ID, ADMIN_CHILD_MENUS, !isMenuEnabled(ADMIN_PARENT_ID))
                    }
                  >
                    <Switch
                      checked={isMenuEnabled(ADMIN_PARENT_ID)}
                      onCheckedChange={(checked) => toggleMenuGroup(ADMIN_PARENT_ID, ADMIN_CHILD_MENUS, checked)}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <span>{t("system.adminSpace")}</span>
                  </label>
                  <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 md:grid-cols-4">
                    {ADMIN_MENU_OPTIONS.filter(
                      (m) => !("parentMenuId" in m) || !m.parentMenuId || isMenuEnabled(m.parentMenuId)
                    ).map((m) => (
                      <label
                        key={m.id}
                        className={`inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-background px-2 py-1.5 text-sm ${
                          !isMenuEnabled(ADMIN_PARENT_ID) ? "opacity-50" : ""
                        }`}
                        onClick={() =>
                          isMenuEnabled(ADMIN_PARENT_ID) &&
                          toggleMenuItem(ADMIN_PARENT_ID, ADMIN_CHILD_MENUS, m.id, !isMenuEnabled(m.id))
                        }
                      >
                        <Switch
                          checked={isMenuEnabled(m.id)}
                          disabled={!isMenuEnabled(ADMIN_PARENT_ID)}
                          onCheckedChange={(checked) =>
                            toggleMenuItem(ADMIN_PARENT_ID, ADMIN_CHILD_MENUS, m.id, checked)
                          }
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span>{m.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <DialogFooter className="mt-4 shrink-0 border-t pt-2">
            <Button variant="outline" onClick={requestCloseEditDialog} disabled={isSaving}>
              {t("cancel")}
            </Button>
            <Button onClick={submitRole} disabled={isSaving || isMenuLoading || menuLoadFailed}>
              {isSaving ? `${t("save")}...` : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
