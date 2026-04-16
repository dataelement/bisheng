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
import { useCallback, useContext, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { CreateLocalMemberDialog } from "./CreateLocalMemberDialog"
import { OrganizationMemberEditDialog } from "./OrganizationMemberEditDialog"

interface MemberTableProps {
  deptId: string
  deptName: string
  onChanged: () => void
}

export function MemberTable({ deptId, deptName, onChanged }: MemberTableProps) {
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
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("system.username")}</TableHead>
            <TableHead>{t("bs:department.memberType")}</TableHead>
            <TableHead>{t("bs:department.userGroups")}</TableHead>
            <TableHead>{t("bs:department.roles")}</TableHead>
            <TableHead>{t("bs:department.updateTime")}</TableHead>
            <TableHead>{t("bs:department.enabled")}</TableHead>
            <TableHead className="min-w-[220px] text-right">{t("operations")}</TableHead>
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
                <TableCell>{m.user_name}</TableCell>
                <TableCell>
                  <Badge variant={m.is_primary === 1 ? "default" : "outline"}>
                    {m.is_primary === 1
                      ? t("bs:department.primary")
                      : t("bs:department.secondary")}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-[150px]">
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
                <TableCell className="max-w-[150px]">
                  {(() => {
                    const text = m.roles.map((r) => r.role_name).join(", ") || "-"
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
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  {fmtTime(m.update_time ?? m.create_time)}
                </TableCell>
                <TableCell>
                  <Switch
                    checked={m.enabled}
                    disabled={isSyncedSource(m.source)}
                    onCheckedChange={(checked) =>
                      handleToggleEnabled(m, Boolean(checked))
                    }
                  />
                </TableCell>
                <TableCell className="text-right">
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
                            className="px-1"
                            disabled={user.user_id === m.user_id}
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
