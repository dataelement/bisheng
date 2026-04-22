import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { Switch } from "@/components/bs-ui/switch"
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
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/bs-ui/tooltip"
import { getDepartmentMembersApi } from "@/controllers/API/department"
import { disableUserApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { userContext } from "@/contexts/userContext"
import UserPwdModal from "@/pages/LoginPage/UserPwdModal"
import { isSyncedSource } from "@/pages/DepartmentPage/constants/syncReadonly"
import { DepartmentMember } from "@/types/api/department"
import { buildMemberDisplayNameMap } from "@/utils/userDisplayName"
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { CreateLocalMemberDialog } from "./CreateLocalMemberDialog"
import { OrganizationMemberEditDialog } from "./OrganizationMemberEditDialog"

interface MemberTableProps {
  deptId: string
  deptName: string
  onChanged: () => void
  /** 父级在部门设置等变更后递增，用于在不切换部门时强制重新拉取成员（如部门管理员 FGA 更新后刷新「角色」列） */
  membersRefreshSignal?: number
}

export function MemberTable({
  deptId,
  deptName,
  onChanged,
  membersRefreshSignal = 0,
}: MemberTableProps) {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  const userPwdModalRef = useRef<{ open: (userId: string | number) => void } | null>(null)
  const [members, setMembers] = useState<DepartmentMember[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState("")
  const [isPrimaryFilter, setIsPrimaryFilter] = useState<string>("all")
  const [addOpen, setAddOpen] = useState(false)
  const [editMember, setEditMember] = useState<DepartmentMember | null>(null)
  const pageRef = useRef(page)
  pageRef.current = page

  const memberDisplayNames = useMemo(
    () => buildMemberDisplayNameMap(members),
    [members]
  )

  const loadMembers = useCallback(() => {
    const params: Record<string, string | number> = {
      page: pageRef.current,
      limit: 20,
      keyword,
    }
    if (isPrimaryFilter !== "all") {
      params.is_primary = parseInt(isPrimaryFilter, 10)
    }
    captureAndAlertRequestErrorHoc(
      getDepartmentMembersApi(deptId, params)
    ).then((res) => {
      if (res) {
        setMembers(res.data)
        setTotal(res.total)
      }
    })
  }, [deptId, keyword, isPrimaryFilter])

  useEffect(() => {
    setPage(1)
    pageRef.current = 1
    loadMembers()
  }, [deptId, keyword, isPrimaryFilter])

  useEffect(() => {
    if (membersRefreshSignal === 0) return
    loadMembers()
  }, [membersRefreshSignal, loadMembers])

  const handlePageChange = useCallback(
    (p: number) => {
      setPage(p)
      pageRef.current = p
      loadMembers()
    },
    [loadMembers]
  )

  const handleToggleEnabled = useCallback(
    (m: DepartmentMember, enabled: boolean) => {
      setMembers((list) =>
        list.map((x) =>
          x.user_id === m.user_id ? { ...x, enabled } : x
        )
      )
      captureAndAlertRequestErrorHoc(
        disableUserApi(m.user_id, enabled ? 0 : 1)
      ).then((res) => {
        if (res === null) {
          loadMembers()
        } else {
          toast({ title: t("prompt"), variant: "success" })
          onChanged()
        }
      })
    },
    [loadMembers, onChanged, t]
  )

  const handleAdded = useCallback(() => {
    setAddOpen(false)
    loadMembers()
    onChanged()
  }, [loadMembers, onChanged])

  const handleEditUser = useCallback((m: DepartmentMember) => {
    setEditMember(m)
  }, [])

  const handleEditClose = useCallback(() => {
    setEditMember(null)
  }, [])

  const handleEditSaved = useCallback(() => {
    setEditMember(null)
    loadMembers()
    onChanged()
  }, [loadMembers, onChanged])

  const fmtTime = (v?: string | Date | null) =>
    v ? String(v).replace("T", " ").slice(0, 19) : "-"

  const memberCols = useMemo(
    () => [
      { defaultWidth: 160, minWidth: 120 },
      { defaultWidth: 120, minWidth: 96 },
      { defaultWidth: 180, minWidth: 120 },
      { defaultWidth: 180, minWidth: 120 },
      { defaultWidth: 160, minWidth: 120 },
      { defaultWidth: 88, minWidth: 72 },
      { defaultWidth: 168, minWidth: 120 },
    ],
    []
  )
  const mrc = useResizableColumns(memberCols)
  const memberLastCol = memberCols.length - 1

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <SearchInput
          placeholder={t("bs:department.searchMember")}
          className="w-[200px]"
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Select value={isPrimaryFilter} onValueChange={setIsPrimaryFilter}>
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("bs:department.all")}</SelectItem>
            <SelectItem value="1">{t("bs:department.primary")}</SelectItem>
            <SelectItem value="0">{t("bs:department.secondary")}</SelectItem>
          </SelectContent>
        </Select>
        <div className="flex-1" />
        <Button size="sm" onClick={() => setAddOpen(true)}>
          {t("bs:department.createLocalUser")}
        </Button>
      </div>

      <TooltipProvider delayDuration={200}>
      <Table
        noScroll
        className="!w-auto min-w-full"
        style={{ tableLayout: "fixed", width: mrc.totalWidth }}
      >
        <TableHeader>
          <TableRow>
            <TableHead {...mrc.getThProps(0)}>
              {t("system.username")}
              <ColumnResizeHandle
                columnIndex={0}
                lastColumn={0 === memberLastCol}
                startResize={mrc.startResize}
              />
            </TableHead>
            <TableHead {...mrc.getThProps(1)}>
              {t("bs:department.memberType", "所属关系")}
              <ColumnResizeHandle
                columnIndex={1}
                lastColumn={1 === memberLastCol}
                startResize={mrc.startResize}
              />
            </TableHead>
            <TableHead {...mrc.getThProps(2)}>
              {t("bs:department.roles")}
              <ColumnResizeHandle
                columnIndex={2}
                lastColumn={2 === memberLastCol}
                startResize={mrc.startResize}
              />
            </TableHead>
            <TableHead {...mrc.getThProps(3)}>
              {t("bs:department.userGroups")}
              <ColumnResizeHandle
                columnIndex={3}
                lastColumn={3 === memberLastCol}
                startResize={mrc.startResize}
              />
            </TableHead>
            <TableHead {...mrc.getThProps(4)}>
              {t("bs:department.updateTime")}
              <ColumnResizeHandle
                columnIndex={4}
                lastColumn={4 === memberLastCol}
                startResize={mrc.startResize}
              />
            </TableHead>
            <TableHead {...mrc.getThProps(5)}>
              {t("bs:department.enabled")}
              <ColumnResizeHandle
                columnIndex={5}
                lastColumn={5 === memberLastCol}
                startResize={mrc.startResize}
              />
            </TableHead>
            <TableHead
              style={mrc.getThProps(6).style}
              className={cname(mrc.getThProps(6).className, "text-right")}
            >
              {t("operations")}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="text-center text-muted-foreground">
                {t("bs:department.noMembers")}
              </TableCell>
            </TableRow>
          ) : (
            members.map((m) => (
              <TableRow key={m.user_id}>
                <TableCell {...mrc.getTdProps(0)} title={memberDisplayNames.get(m.user_id) ?? m.user_name}>
                  {memberDisplayNames.get(m.user_id) ?? m.user_name}
                </TableCell>
                <TableCell {...mrc.getTdProps(1)}>
                  <Badge variant={m.is_primary === 1 ? "default" : "outline"}>
                    {m.is_primary === 1
                      ? t("bs:department.primary")
                      : t("bs:department.secondary")}
                  </Badge>
                </TableCell>
                <TableCell {...mrc.getTdProps(2)}>
                  {(() => {
                    const roleNames: string[] = []
                    if (m.is_department_admin) {
                      roleNames.push(t("bs:department.deptAdminRoleName"))
                    }
                    roleNames.push(...m.roles.map((r) => r.role_name))
                    const text = roleNames.join(", ") || "-"
                    return (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-default truncate">{text}</div>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-sm whitespace-pre-wrap">
                          {text}
                        </TooltipContent>
                      </Tooltip>
                    )
                  })()}
                </TableCell>
                <TableCell {...mrc.getTdProps(3)}>
                  {(() => {
                    const text =
                      m.user_groups.map((g) => g.group_name).join(", ") || "-"
                    return (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-default truncate">{text}</div>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-sm whitespace-pre-wrap">
                          {text}
                        </TooltipContent>
                      </Tooltip>
                    )
                  })()}
                </TableCell>
                <TableCell {...mrc.getTdProps(4)} className="whitespace-nowrap text-muted-foreground">
                  {fmtTime(m.update_time ?? m.create_time)}
                </TableCell>
                <TableCell {...mrc.getTdProps(5)}>
                  <Switch
                    checked={m.enabled}
                    disabled={isSyncedSource(m.source)}
                    onCheckedChange={(checked) =>
                      handleToggleEnabled(m, Boolean(checked))
                    }
                  />
                </TableCell>
                <TableCell {...mrc.getTdProps(6)} className="text-right">
                  {(() => {
                    const isSuperAdmin = m.roles.some((role) => role.id === 1)
                    const canResetPwd = user.role === "admin"
                    return (
                      <div className="flex flex-wrap items-center justify-end gap-x-1">
                        {isSuperAdmin ? (
                          <Button variant="link" size="sm" disabled className="px-1">
                            {t("edit")}
                          </Button>
                        ) : (
                          <Button
                            variant="link"
                            size="sm"
                            className="px-1 disabled:cursor-not-allowed disabled:text-muted-foreground disabled:opacity-60"
                            disabled={user.user_id === m.user_id || !m.enabled}
                            onClick={() => handleEditUser(m)}
                          >
                            {t("edit")}
                          </Button>
                        )}
                        {canResetPwd && (
                          <Button
                            variant="link"
                            size="sm"
                            className="px-1"
                            onClick={() =>
                              userPwdModalRef.current?.open(m.user_id)
                            }
                          >
                            {t("system.resetPwd")}
                          </Button>
                        )}
                      </div>
                    )
                  })()}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      </TooltipProvider>

      <div className="mt-4 flex justify-end">
        <AutoPagination
          page={page}
          pageSize={20}
          total={total}
          showTotal={true}
          onChange={handlePageChange}
        />
      </div>

      {addOpen && (
        <CreateLocalMemberDialog
          deptId={deptId}
          deptName={deptName}
          onCreated={handleAdded}
          onClose={() => setAddOpen(false)}
        />
      )}

      <OrganizationMemberEditDialog
        open={Boolean(editMember)}
        deptId={deptId}
        member={editMember}
        onClose={handleEditClose}
        onSaved={handleEditSaved}
      />
      <UserPwdModal ref={userPwdModalRef} />
    </div>
  )
}
