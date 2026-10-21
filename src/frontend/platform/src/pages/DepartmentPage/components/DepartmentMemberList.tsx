import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Switch } from "@/components/bs-ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table"
import { ColumnResizeHandle, type UseResizableColumnsResult } from "@/components/bs-ui/table/useResizableColumns"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip"
import { cname } from "@/components/bs-ui/utils"
import type { DepartmentMember } from "@/types/api/department"
import { buildMemberDisplayNameMap } from "@/utils/userDisplayName"
import { useMemo } from "react"
import { useTranslation } from "react-i18next"

interface DepartmentMemberListProps {
  members: DepartmentMember[]
  mrc: UseResizableColumnsResult
  memberLastCol: number
  highlightUserId?: number | null
  isArchived: boolean
  isPlatformAdmin: boolean
  currentUserId?: number
  onToggleEnabled: (member: DepartmentMember, enabled: boolean) => void
  onEditUser: (member: DepartmentMember) => void
  onResetPassword: (userId: number) => void
}

export function DepartmentMemberList({
  members, mrc, memberLastCol, highlightUserId, isArchived,
  isPlatformAdmin, currentUserId, onToggleEnabled, onEditUser, onResetPassword,
}: DepartmentMemberListProps) {
  const { t } = useTranslation()
  const memberDisplayNames = useMemo(() => buildMemberDisplayNameMap(members), [members])
  const fmtTime = (v?: string | Date | null) =>
    v ? String(v).replace("T", " ").slice(0, 19) : "-"

  return (
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
              {t("bs:department.memberType")}
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
                    disabled={
                      isArchived
                      || (!m.enabled && !!m.disable_source && !isPlatformAdmin)
                    }
                    onCheckedChange={(checked) =>
                      onToggleEnabled(m, Boolean(checked))
                    }
                  />
                </TableCell>
                <TableCell {...mrc.getTdProps(6)} className="text-right">
                  {(() => {
                    const isSuperAdmin = m.roles.some((role) => role.id === 1)
                    const canResetPwd = isPlatformAdmin
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
                            disabled={isArchived || currentUserId === m.user_id || !m.enabled}
                            onClick={() => onEditUser(m)}
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
                              !isArchived && onResetPassword(m.user_id)
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
  )
}
