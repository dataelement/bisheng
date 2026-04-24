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
import {
  getDepartmentMembersApi,
  searchGlobalMembersApi,
  type GlobalMemberSearchRow,
} from "@/controllers/API/department"
import { disableUserApi } from "@/controllers/API/user"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { userContext } from "@/contexts/userContext"
import UserPwdModal from "@/pages/LoginPage/UserPwdModal"
import { isSyncedSource } from "@/pages/DepartmentPage/constants/syncReadonly"
import { DepartmentMember } from "@/types/api/department"
import { buildMemberDisplayNameMap } from "@/utils/userDisplayName"
import { Loader2 } from "lucide-react"
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { CreateLocalMemberDialog } from "./CreateLocalMemberDialog"
import { OrganizationMemberEditDialog } from "./OrganizationMemberEditDialog"

interface MemberTableProps {
  deptId: string
  deptName: string
  isArchived?: boolean
  onChanged: () => void
  /** 父级在部门设置等变更后递增，用于在不切换部门时强制重新拉取成员（如部门管理员 FGA 更新后刷新「角色」列） */
  membersRefreshSignal?: number
  /** 全组织搜索定位后高亮该用户行 */
  highlightUserId?: number | null
  onHighlightConsumed?: () => void
  /** 点击全组织搜索结果时，通知父级切换部门并滚动左侧树 */
  onRequestLocateMember?: (payload: {
    primaryDeptDeptId: string
    userId: number
  }) => void
}

export function MemberTable({
  deptId,
  deptName,
  isArchived = false,
  onChanged,
  membersRefreshSignal = 0,
  highlightUserId = null,
  onHighlightConsumed,
  onRequestLocateMember,
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
  const [memberScope, setMemberScope] = useState<"dept" | "org">("dept")
  const [globalRows, setGlobalRows] = useState<GlobalMemberSearchRow[]>([])
  const [globalTotal, setGlobalTotal] = useState(0)
  const [globalPage, setGlobalPage] = useState(1)
  const [globalLoading, setGlobalLoading] = useState(false)
  const pageRef = useRef(page)
  pageRef.current = page

  useEffect(() => {
    setMemberScope("dept")
    setGlobalPage(1)
    setGlobalRows([])
    setGlobalTotal(0)
  }, [deptId])

  const memberDisplayNames = useMemo(
    () => buildMemberDisplayNameMap(members),
    [members]
  )

  const loadMembers = useCallback(() => {
    if (memberScope !== "dept") return
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
  }, [deptId, keyword, isPrimaryFilter, memberScope])

  useEffect(() => {
    if (memberScope !== "dept") return
    setPage(1)
    pageRef.current = 1
    loadMembers()
  }, [deptId, keyword, isPrimaryFilter, memberScope, loadMembers])

  useEffect(() => {
    if (membersRefreshSignal === 0) return
    if (memberScope !== "dept") return
    loadMembers()
  }, [membersRefreshSignal, loadMembers, memberScope])

  const loadGlobalMembers = useCallback(() => {
    const kw = keyword.trim()
    if (!kw) {
      setGlobalRows([])
      setGlobalTotal(0)
      setGlobalLoading(false)
      return
    }
    setGlobalLoading(true)
    captureAndAlertRequestErrorHoc(
      searchGlobalMembersApi({ keyword: kw, page: globalPage, limit: 20 })
    ).then((res) => {
      setGlobalLoading(false)
      if (res) {
        setGlobalRows(res.data)
        setGlobalTotal(res.total)
      }
    })
  }, [keyword, globalPage])

  useEffect(() => {
    if (memberScope !== "org") return
    setGlobalPage(1)
  }, [keyword, memberScope])

  useEffect(() => {
    if (memberScope !== "org") return
    const t = window.setTimeout(() => void loadGlobalMembers(), 280)
    return () => window.clearTimeout(t)
  }, [memberScope, keyword, globalPage, loadGlobalMembers])

  useEffect(() => {
    if (memberScope !== "dept" || highlightUserId == null) return
    const hit = members.some((m) => m.user_id === highlightUserId)
    if (!hit) return
    const t = window.setTimeout(() => {
      const el = document.querySelector(
        `[data-member-row="${highlightUserId}"]`
      )
      el?.scrollIntoView({ block: "nearest", behavior: "smooth" })
      onHighlightConsumed?.()
    }, 120)
    return () => window.clearTimeout(t)
  }, [members, highlightUserId, memberScope, onHighlightConsumed])

  const handlePageChange = useCallback(
    (p: number) => {
      setPage(p)
      pageRef.current = p
      loadMembers()
    },
    [loadMembers]
  )

  const handleGlobalPageChange = useCallback((p: number) => {
    setGlobalPage(p)
  }, [])

  const handleToggleEnabled = useCallback(
    (m: DepartmentMember, enabled: boolean) => {
      if (isArchived) return
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
    [isArchived, loadMembers, onChanged, t]
  )

  const handleAdded = useCallback(() => {
    setAddOpen(false)
    loadMembers()
    onChanged()
  }, [loadMembers, onChanged])

  const handleEditUser = useCallback((m: DepartmentMember) => {
    if (isArchived) return
    setEditMember(m)
  }, [isArchived])

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
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-0.5 rounded-md bg-muted p-0.5">
          <button
            type="button"
            className={cname(
              "rounded px-3 py-1.5 text-sm transition-colors",
              memberScope === "dept"
                ? "bg-background text-foreground shadow"
                : "text-muted-foreground hover:text-foreground"
            )}
            onClick={() => setMemberScope("dept")}
          >
            {t("bs:department.memberSearchScopeCurrent")}
          </button>
          <button
            type="button"
            className={cname(
              "rounded px-3 py-1.5 text-sm transition-colors",
              memberScope === "org"
                ? "bg-background text-foreground shadow"
                : "text-muted-foreground hover:text-foreground"
            )}
            onClick={() => setMemberScope("org")}
          >
            {t("bs:department.memberSearchScopeOrg")}
          </button>
        </div>
        <SearchInput
          placeholder={t("bs:department.searchMember")}
          className="w-[200px]"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        {memberScope === "dept" && (
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
        )}
        <div className="flex-1" />
        {memberScope === "dept" && (
          <Button
            size="sm"
            disabled={isArchived}
            className="disabled:cursor-not-allowed"
            onClick={() => {
              if (!isArchived) setAddOpen(true)
            }}
          >
            {t("bs:department.createLocalUser")}
          </Button>
        )}
      </div>
      {memberScope === "org" && (
        <p className="mb-3 text-xs text-muted-foreground">
          {t("bs:department.globalMemberSearchHint")}
        </p>
      )}

      {memberScope === "org" && (
        <div className="mb-4 rounded-md border">
          {globalLoading && globalRows.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("bs:department.memberEditLoading")}
            </div>
          ) : !keyword.trim() ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              {t("bs:department.globalMemberEmptyKeyword")}
            </div>
          ) : globalRows.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              {t("bs:department.globalMemberNoResults")}
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[160px]">{t("system.username")}</TableHead>
                    <TableHead>{t("bs:department.globalMemberPrimaryPath")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {globalRows.map((r) => (
                    <TableRow
                      key={`${r.user_id}-${r.primary_department_dept_id}`}
                      className={cname(
                        onRequestLocateMember && "cursor-pointer hover:bg-accent/60"
                      )}
                      onClick={() => {
                        setMemberScope("dept")
                        onRequestLocateMember?.({
                          primaryDeptDeptId: r.primary_department_dept_id,
                          userId: r.user_id,
                        })
                      }}
                    >
                      <TableCell className="font-medium">{r.user_name}</TableCell>
                      <TableCell
                        className="max-w-md truncate text-muted-foreground"
                        title={r.primary_department_path}
                      >
                        {r.primary_department_path || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex justify-end border-t px-2 py-2">
                <AutoPagination
                  page={globalPage}
                  pageSize={20}
                  total={globalTotal}
                  showTotal
                  onChange={handleGlobalPageChange}
                />
              </div>
            </>
          )}
        </div>
      )}

      {memberScope === "dept" && (
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
              <TableRow
                key={m.user_id}
                data-member-row={m.user_id}
                className={cname(
                  highlightUserId != null && m.user_id === highlightUserId
                    ? "bg-accent/50"
                    : ""
                )}
              >
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
                    disabled={isArchived || isSyncedSource(m.source)}
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
                            disabled={isArchived || user.user_id === m.user_id || !m.enabled}
                            onClick={() => handleEditUser(m)}
                          >
                            {t("edit")}
                          </Button>
                        )}
                        {canResetPwd && (
                          <Button
                            variant="link"
                            size="sm"
                            className="px-1 disabled:cursor-not-allowed disabled:text-muted-foreground disabled:opacity-60"
                            disabled={isArchived}
                            onClick={() =>
                              !isArchived && userPwdModalRef.current?.open(m.user_id)
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
      )}

      {memberScope === "dept" && (
      <div className="mt-4 flex justify-end">
        <AutoPagination
          page={page}
          pageSize={20}
          total={total}
          showTotal={true}
          onChange={handlePageChange}
        />
      </div>
      )}

      {addOpen && !isArchived && (
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
