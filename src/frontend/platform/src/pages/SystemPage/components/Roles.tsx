import { PlusIcon } from "@/components/bs-icons/plus"
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { getDepartmentTreeApi } from "@/controllers/API/department"
import {
  createRoleV2Api,
  deleteRoleV2Api,
  getRoleMenuV2Api,
  getRolesPageApi,
  updateRoleMenuV2Api,
  updateRoleV2Api,
} from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { ROLE } from "@/types/api/user"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

export default function Roles() {
  const { t } = useTranslation()
  const [roles, setRoles] = useState<ROLE[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState("")
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([])
  const [editOpen, setEditOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [activeRole, setActiveRole] = useState<ROLE | null>(null)
  const [roleName, setRoleName] = useState("")
  const [departmentId, setDepartmentId] = useState<string>("none")
  const [quotaFileUnlimited, setQuotaFileUnlimited] = useState(true)
  const [quotaFileGb, setQuotaFileGb] = useState("500")
  const [quotaChannelUnlimited, setQuotaChannelUnlimited] = useState(false)
  const [quotaChannelCount, setQuotaChannelCount] = useState("10")
  const [menuIds, setMenuIds] = useState<string[]>([])

  const MENU_OPTIONS = useMemo(
    () => [
      { id: "workstation", label: t("menu.workspace") },
      { id: "admin", label: t("menu.system") },
      { id: "build", label: t("menu.skills") },
      { id: "knowledge", label: t("menu.knowledge") },
      { id: "knowledge_space", label: t("system.spaceName") },
      { id: "model", label: t("menu.models") },
      { id: "tool", label: "Tool" },
      { id: "channel", label: "Channel" },
      { id: "evaluation", label: t("menu.evaluation") },
      { id: "dataset", label: t("menu.dataset") },
      { id: "mark_task", label: t("menu.annotation") },
      { id: "board", label: t("menu.board") },
    ],
    [t]
  )

  const flatTree = (nodes: any[]): { id: number; name: string }[] => {
    const out: { id: number; name: string }[] = []
    const walk = (arr: any[], parent = "") => {
      arr.forEach((n) => {
        const path = parent ? `${parent} / ${n.name}` : n.name
        out.push({ id: n.id, name: path })
        walk(n.children || [], path)
      })
    }
    walk(nodes)
    return out
  }

  const loadDepartments = async () => {
    const res = await captureAndAlertRequestErrorHoc(getDepartmentTreeApi())
    if (res) setDepartments(flatTree(res))
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
    setActiveRole(null)
    setRoleName("")
    setDepartmentId("none")
    setQuotaFileUnlimited(true)
    setQuotaFileGb("500")
    setQuotaChannelUnlimited(false)
    setQuotaChannelCount("10")
    setEditOpen(true)
  }

  const openEdit = (role: ROLE) => {
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
    setEditOpen(true)
  }

  const submitRole = async () => {
    if (!roleName.trim()) return
    const fileLimit = quotaFileUnlimited ? -1 : Math.max(0, Number(quotaFileGb || 0))
    const channelLimit = quotaChannelUnlimited ? -1 : Math.max(0, Number(quotaChannelCount || 0))
    const payload = {
      role_name: roleName.trim(),
      department_id: departmentId === "none" ? null : Number(departmentId),
      quota_config: {
        knowledge_space_file: fileLimit,
        channel: channelLimit,
      },
      remark: "PRD 2.5 role",
    }
    const res = activeRole
      ? await captureAndAlertRequestErrorHoc(updateRoleV2Api(activeRole.id, payload))
      : await captureAndAlertRequestErrorHoc(createRoleV2Api(payload))
    if (res !== null) {
      setEditOpen(false)
      loadRoles()
    }
  }

  const onDelete = (item: ROLE) => {
    bsConfirm({
      desc: `${t("system.confirmText")}【${item.role_name}】?`,
      okTxt: t("delete"),
      onOk: (next) => {
        captureAndAlertRequestErrorHoc(deleteRoleV2Api(item.id)).then((res) => {
          if (res !== null) loadRoles()
          next()
        })
      },
    })
  }

  const openMenu = async (item: ROLE) => {
    setActiveRole(item)
    const res = await captureAndAlertRequestErrorHoc(getRoleMenuV2Api(item.id))
    setMenuIds(Array.isArray(res) ? res : [])
    setMenuOpen(true)
  }

  const saveMenu = async () => {
    if (!activeRole) return
    const res = await captureAndAlertRequestErrorHoc(updateRoleMenuV2Api(activeRole.id, menuIds))
    if (res !== null) setMenuOpen(false)
  }

  const toggleMenu = (id: string) => {
    setMenuIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  return (
    <div className="relative">
      <div className="h-[calc(100vh-128px)] overflow-y-auto pb-10 pt-2">
        <div className="mb-3 flex items-center justify-between">
          <div className="w-[220px]">
            <SearchInput
              placeholder={t("system.roleName")}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </div>
          <Button className="flex justify-around" onClick={openCreate}>
            <PlusIcon className="text-primary" />
            <span className="mx-4 text-[#fff]">{t("create")}</span>
          </Button>
        </div>
        <Table className="mb-6">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[180px]">{t("system.roleName")}</TableHead>
              <TableHead className="w-[110px]">{t("system.roleType")}</TableHead>
              <TableHead>{t("system.roleScope")}</TableHead>
              <TableHead className="w-[120px]">{t("system.userCount")}</TableHead>
              <TableHead className="w-[120px]">{t("system.creator")}</TableHead>
              <TableHead className="w-[170px]">{t("createTime")}</TableHead>
              <TableHead className="w-[170px]">{t("system.changeTime")}</TableHead>
              <TableHead className="text-right">{t("operations")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {roles.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-gray-400">
                  {t("build.empty")}
                </TableCell>
              </TableRow>
            ) : (
              roles.map((el) => (
                <TableRow key={el.id}>
                  <TableCell className="font-medium">{el.role_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {el.role_type === "global" ? t("system.scopeGlobal") : t("system.scopeDept")}
                    </Badge>
                  </TableCell>
                  <TableCell>{el.department_name || "-"}</TableCell>
                  <TableCell>{el.user_count ?? "-"}</TableCell>
                  <TableCell>{el.role_type === "global" ? t("system.systemPreset") : t("system.deptAdminCreated")}</TableCell>
                  <TableCell>{fmtTime(el.create_time)}</TableCell>
                  <TableCell>{fmtTime(el.update_time)}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="link"
                      disabled={Boolean(el.is_readonly)}
                      className="px-0 pl-4"
                      onClick={() => openEdit(el)}
                    >
                      {t("edit")}
                    </Button>
                    <Button variant="link" className="px-0 pl-4" onClick={() => openMenu(el)}>
                      {t("system.adminMenuAuthorization")}
                    </Button>
                    <Button
                      variant="link"
                      disabled={Boolean(el.is_readonly) || [1, 2].includes(el.id)}
                      className="px-0 pl-4 text-red-500"
                      onClick={() => onDelete(el)}
                    >
                      {t("delete")}
                    </Button>
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
          onChange={(p) => {
            setPage(p)
            loadRoles(p, keyword)
          }}
        />
      </div>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{activeRole ? t("edit") : t("create")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>{t("system.roleName")}</Label>
              <Input value={roleName} onChange={(e) => setRoleName(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label>{t("system.roleScope")}</Label>
              <Select value={departmentId} onValueChange={setDepartmentId}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{t("system.scopeGlobal")}</SelectItem>
                  {departments.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>
                      {d.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="rounded-md border p-3">
              <Label>{t("system.knowledgeSpaceFileUploadLimit")}</Label>
              <div className="mt-2 flex items-center gap-3">
                <Checkbox
                  checked={quotaFileUnlimited}
                  onCheckedChange={(v) => setQuotaFileUnlimited(Boolean(v))}
                />
                <span className="text-sm">{t("system.unlimited")}</span>
                {!quotaFileUnlimited && (
                  <Input
                    type="number"
                    min={0}
                    value={quotaFileGb}
                    onChange={(e) => setQuotaFileGb(e.target.value)}
                    className="w-[120px]"
                  />
                )}
                {!quotaFileUnlimited && <span className="text-sm">GB</span>}
              </div>
            </div>
            <div className="rounded-md border p-3">
              <Label>{t("system.channelQuotaLimit")}</Label>
              <div className="mt-2 flex items-center gap-3">
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
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={submitRole}>{t("save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("system.adminMenuAuthorization")}</DialogTitle>
          </DialogHeader>
          <div className="max-h-80 space-y-2 overflow-auto">
            <p className="mb-2 mt-1 text-xs text-muted-foreground">{t("system.workbenchMenuAuthorization")}</p>
            {MENU_OPTIONS.filter((x) => x.id === "workstation").map((m) => (
              <label key={m.id} className="flex items-center gap-2 text-sm">
                <Checkbox checked={menuIds.includes(m.id)} onCheckedChange={() => toggleMenu(m.id)} />
                <span>{m.label}</span>
              </label>
            ))}
            <p className="mb-2 mt-3 text-xs text-muted-foreground">{t("system.adminMenuAuthorization")}</p>
            {MENU_OPTIONS.filter((x) => x.id !== "workstation").map((m) => (
              <label key={m.id} className="flex items-center gap-2 text-sm">
                <Checkbox checked={menuIds.includes(m.id)} onCheckedChange={() => toggleMenu(m.id)} />
                <span>{m.label}</span>
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMenuOpen(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={saveMenu}>{t("save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
