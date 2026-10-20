import { Button, SearchInput } from '@bisheng/ui';
import { Segmented, Tooltip as SharedTooltip, Switch, Tag } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";



import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { ColumnResizeHandle } from "@/components/bs-ui/table/useResizableColumns";
import { TooltipProvider } from "@/components/bs-ui/tooltip";
import { cname } from "@/components/bs-ui/utils";
import UserPwdModal from "@/pages/LoginPage/UserPwdModal";

import { CreateLocalMemberDialog } from "./CreateLocalMemberDialog";
import type { useMemberTableController } from "./MemberTable";
import { OrganizationMemberEditDialog } from "./OrganizationMemberEditDialog";
interface MemberTableViewProps {
  controller: ReturnType<typeof useMemberTableController>;
}
export function MemberTableView({ controller }: MemberTableViewProps) {
  const {
    memberLastCol,
    memberScope,
    setMemberScope,
    t,
    keyword,
    setKeyword,
    isPrimaryFilter,
    setIsPrimaryFilter,
    isArchived,
    setAddOpen,
    directAdmins,
    inheritedAdmins,
    globalLoading,
    globalRows,
    onRequestLocateMember,
    globalPage,
    globalTotal,
    handleGlobalPageChange,
    mrc,
    members,
    highlightUserId,
    memberDisplayNames,
    fmtTime,
    user,
    handleToggleEnabled,
    handleEditUser,
    userPwdModalRef,
    page,
    total,
    handlePageChange,
    addOpen,
    deptId,
    deptName,
    handleAdded,
    editMember,
    handleEditClose,
    handleEditSaved,
  } = controller;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Segmented
          value={memberScope}
          onChange={(value) => setMemberScope(value as "dept" | "org")}
          options={[
            { value: "dept", label: t("bs:department.memberSearchScopeCurrent") },
            { value: "org", label: t("bs:department.memberSearchScopeOrg") },
          ]}
        />
        <SearchInput placeholder={t("bs:department.searchMember")} value={keyword} onChange={(e) => setKeyword(e.target.value)} className={"w-[200px]"} />
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
          <Button size="small" disabled={isArchived} className="disabled:cursor-not-allowed" onClick={() => {
              if (!isArchived) setAddOpen(true);
            }}>
            {t("bs:department.createLocalUser")}
          </Button>
        )}
      </div>
      {memberScope === "org" && (
        <p className="mb-3 text-xs text-muted-foreground">{t("bs:department.globalMemberSearchHint")}</p>
      )}

      {memberScope === "dept" && (directAdmins.length > 0 || inheritedAdmins.length > 0) && (
        <div className="mb-3 rounded-md border bg-muted/20 px-3 py-2">
          {directAdmins.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-medium text-muted-foreground">{t("bs:department.directAdmins")}</span>
              {directAdmins.map((admin) => (
                <Tag size="small" key={admin.user_id} color="default">
                  {admin.user_name}
                </Tag>
              ))}
            </div>
          )}
          {inheritedAdmins.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-medium text-muted-foreground">
                {t("bs:department.inheritedAdmins")}
              </span>
              {inheritedAdmins.map((admin) => (
                <TooltipProvider key={`${admin.user_id}-${admin.sourceDeptName}`} delayDuration={200}>
                  <SharedTooltip
                    content={t("bs:department.inheritedAdminSource", {
                      department: admin.sourceDeptName,
                    })}
                  >
                    <span tabIndex={0} className="inline-flex cursor-default">
                      <Tag size="small" color="default">{admin.user_name}</Tag>
                    </span>
                  </SharedTooltip>
                </TooltipProvider>
              ))}
            </div>
          )}
        </div>
      )}

      {memberScope === "org" && (
        <div className="mb-4 rounded-md border">
          {globalLoading && globalRows.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Outlined.Loading className="h-4 w-4 animate-spin" />
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
                        onRequestLocateMember && "cursor-pointer hover:bg-accent/60",
                        r.enabled === false && "opacity-90",
                      )}
                      onClick={() => {
                        setMemberScope("dept");
                        onRequestLocateMember?.({
                          primaryDeptDeptId: r.primary_department_dept_id,
                          userId: r.user_id,
                        });
                      }}
                    >
                      <TableCell className="font-medium">
                        <span className="inline-flex flex-wrap items-center gap-1.5">
                          {r.user_name}
                          {r.enabled === false && (
                            <Tag size="small" dot color="danger">
                              {t("bs:department.disabled")}
                            </Tag>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="max-w-md truncate text-muted-foreground" title={r.primary_department_path}>
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
          <Table noScroll className="!w-auto min-w-full" style={{ tableLayout: "fixed", width: mrc.totalWidth }}>
            <TableHeader>
              <TableRow>
                <TableHead {...mrc.getThProps(0)}>
                  {t("system.username")}
                  <ColumnResizeHandle columnIndex={0} lastColumn={0 === memberLastCol} startResize={mrc.startResize} />
                </TableHead>
                <TableHead {...mrc.getThProps(1)}>
                  {t("bs:department.memberType")}
                  <ColumnResizeHandle columnIndex={1} lastColumn={1 === memberLastCol} startResize={mrc.startResize} />
                </TableHead>
                <TableHead {...mrc.getThProps(2)}>
                  {t("bs:department.roles")}
                  <ColumnResizeHandle columnIndex={2} lastColumn={2 === memberLastCol} startResize={mrc.startResize} />
                </TableHead>
                <TableHead {...mrc.getThProps(3)}>
                  {t("bs:department.userGroups")}
                  <ColumnResizeHandle columnIndex={3} lastColumn={3 === memberLastCol} startResize={mrc.startResize} />
                </TableHead>
                <TableHead {...mrc.getThProps(4)}>
                  {t("bs:department.updateTime")}
                  <ColumnResizeHandle columnIndex={4} lastColumn={4 === memberLastCol} startResize={mrc.startResize} />
                </TableHead>
                <TableHead {...mrc.getThProps(5)}>
                  {t("bs:department.enabled")}
                  <ColumnResizeHandle columnIndex={5} lastColumn={5 === memberLastCol} startResize={mrc.startResize} />
                </TableHead>
                <TableHead style={mrc.getThProps(6).style} className={cname(mrc.getThProps(6).className, "text-right")}>
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
                    className={cname(highlightUserId != null && m.user_id === highlightUserId ? "bg-accent/50" : "")}
                  >
                    <TableCell {...mrc.getTdProps(0)} title={memberDisplayNames.get(m.user_id) ?? m.user_name}>
                      {memberDisplayNames.get(m.user_id) ?? m.user_name}
                    </TableCell>
                    <TableCell {...mrc.getTdProps(1)}>
                      <Tag size="small" color={m.is_primary === 1 ? "brand" : "default"}>
                        {m.is_primary === 1 ? t("bs:department.primary") : t("bs:department.secondary")}
                      </Tag>
                    </TableCell>
                    <TableCell {...mrc.getTdProps(2)}>
                      {(() => {
                        const roleNames: string[] = [];
                        if (m.is_department_admin) {
                          roleNames.push(t("bs:department.deptAdminRoleName"));
                        }
                        roleNames.push(...m.roles.map((r) => r.role_name));
                        const text = roleNames.join(", ") || "-";
                        return (
                          <SharedTooltip content={text}>
                            <div className="cursor-default truncate">{text}</div>
                          </SharedTooltip>
                        );
                      })()}
                    </TableCell>
                    <TableCell {...mrc.getTdProps(3)}>
                      {(() => {
                        const text = m.user_groups.map((g) => g.group_name).join(", ") || "-";
                        return (
                          <SharedTooltip content={text}>
                            <div className="cursor-default truncate">{text}</div>
                          </SharedTooltip>
                        );
                      })()}
                    </TableCell>
                    <TableCell {...mrc.getTdProps(4)} className="whitespace-nowrap text-muted-foreground">
                      {fmtTime(m.update_time ?? m.create_time)}
                    </TableCell>
                    <TableCell {...mrc.getTdProps(5)}>
                      <Switch
                        checked={m.enabled}
                        disabled={isArchived || (!m.enabled && !!m.disable_source && user?.role !== "admin")}
                        onCheckedChange={(checked) => handleToggleEnabled(m, Boolean(checked))}
                      />
                    </TableCell>
                    <TableCell {...mrc.getTdProps(6)} className="text-right">
                      {(() => {
                        const isSuperAdmin = m.roles.some((role) => role.id === 1);
                        const canResetPwd = user.role === "admin";
                        return (
                          <div className="flex flex-wrap items-center justify-end gap-x-1">
                            {isSuperAdmin ? (
                              <Button variant="link" size="small" disabled className="px-1">
                                {t("edit")}
                              </Button>
                            ) : (
                              <Button variant="link" size="small" className="px-1 disabled:cursor-not-allowed disabled:text-muted-foreground disabled:opacity-60" disabled={isArchived || user.user_id === m.user_id || !m.enabled} onClick={() => handleEditUser(m)}>
                                {t("edit")}
                              </Button>
                            )}
                            {canResetPwd && (
                              <Button variant="link" size="small" className="px-1 disabled:cursor-not-allowed disabled:text-muted-foreground disabled:opacity-60" disabled={isArchived} onClick={() => !isArchived && userPwdModalRef.current?.open(m.user_id)}>
                                {t("system.resetPwd")}
                              </Button>
                            )}
                          </div>
                        );
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
          <AutoPagination page={page} pageSize={20} total={total} showTotal={true} onChange={handlePageChange} />
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
  );
}
