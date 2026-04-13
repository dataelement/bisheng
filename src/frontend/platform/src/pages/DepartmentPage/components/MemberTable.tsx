import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
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
  getDepartmentMembersApi,
  removeDepartmentMemberApi,
} from "@/controllers/API/department"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { DepartmentMember } from "@/types/api/department"
import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { AddMemberDialog } from "./AddMemberDialog"

interface MemberTableProps {
  deptId: string
  onChanged: () => void
}

export function MemberTable({ deptId, onChanged }: MemberTableProps) {
  const { t } = useTranslation()
  const [members, setMembers] = useState<DepartmentMember[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState("")
  const [isPrimaryFilter, setIsPrimaryFilter] = useState<string>("all")
  const [addOpen, setAddOpen] = useState(false)
  const pageRef = useRef(page)
  pageRef.current = page

  const loadMembers = useCallback(() => {
    const params: any = { page: pageRef.current, limit: 20, keyword }
    if (isPrimaryFilter !== "all") {
      params.is_primary = parseInt(isPrimaryFilter)
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

  const handleRemove = useCallback(
    (userId: number, userName: string) => {
      bsConfirm({
        title: t("bs:department.removeMember"),
        desc: t("bs:department.confirmRemoveMember"),
        onOk: (next) => {
          captureAndAlertRequestErrorHoc(
            removeDepartmentMemberApi(deptId, userId)
          ).then((res) => {
            if (res !== null) {
              toast({ title: t("bs:department.removeMember"), variant: "success" })
              loadMembers()
              onChanged()
            }
            next()
          })
        },
      })
    },
    [deptId, loadMembers, onChanged, t]
  )

  const handleAdded = useCallback(() => {
    setAddOpen(false)
    loadMembers()
    onChanged()
  }, [loadMembers, onChanged])

  return (
    <div>
      {/* Toolbar */}
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
          {t("bs:department.addMember")}
        </Button>
      </div>

      {/* Table */}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("system.username")}</TableHead>
            <TableHead>{t("bs:department.memberType")}</TableHead>
            <TableHead>{t("bs:department.userGroups")}</TableHead>
            <TableHead>{t("bs:department.roles")}</TableHead>
            <TableHead>{t("bs:department.enabled")}</TableHead>
            <TableHead className="w-[80px]">{t("operations")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">
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
                <TableCell className="max-w-[150px] truncate">
                  {m.user_groups.map((g) => g.group_name).join(", ") || "-"}
                </TableCell>
                <TableCell className="max-w-[150px] truncate">
                  {m.roles.map((r) => r.role_name).join(", ") || "-"}
                </TableCell>
                <TableCell>
                  <Badge variant={m.enabled ? "default" : "destructive"}>
                    {m.enabled ? t("bs:department.enabled") : t("bs:department.disabled")}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Button
                    variant="link"
                    size="sm"
                    className="text-destructive"
                    onClick={() => handleRemove(m.user_id, m.user_name)}
                  >
                    {t("bs:department.removeMember")}
                  </Button>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {/* Pagination */}
      <div className="mt-4 flex justify-end">
        <AutoPagination
          page={page}
          pageSize={20}
          total={total}
          onChange={handlePageChange}
        />
      </div>

      {/* Add member dialog */}
      {addOpen && (
        <AddMemberDialog
          deptId={deptId}
          onAdded={handleAdded}
          onClose={() => setAddOpen(false)}
        />
      )}
    </div>
  )
}
