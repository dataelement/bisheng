import {
  Button,
  Checkbox,
  Dropdown,
  DropdownItem,
  Pagination,
  Select,
  Switch,
  Tag,
  Tooltip as SharedTooltip,
  TooltipProvider as SharedTooltipProvider,
  toast,
} from "@bisheng/ui";
import { Outlined } from 'bisheng-icons';
import { copyText } from '@/utils';
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { departmentDisplayName } from "@/components/bs-comp/department/departmentDisplayName";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import { ColumnResizeHandle } from "@/components/bs-ui/table/useResizableColumns";
import { cname } from "@/components/bs-ui/utils";
import UserPwdModal from "@/pages/LoginPage/UserPwdModal";
import type { DepartmentMember } from "@/types/api/department";
import { MemberRoleSummary } from "./MemberRoleSummary";
import { CreateLocalMemberDialog } from "./CreateLocalMemberDialog";
import type { useMemberTableController } from "./MemberTable";
import { OrganizationMemberEditDialog } from "./OrganizationMemberEditDialog";

interface MemberTableViewProps {
  controller: ReturnType<typeof useMemberTableController>;
}
export function MemberTableView({ controller }: MemberTableViewProps) {
  const {
    memberLastCol,
    t,
    isPrimaryFilter,
    setIsPrimaryFilter,
    isArchived,
    setAddOpen,
    directAdmins,
    inheritedAdmins,
    mrc,
    members,
    loading,
    highlightUserId,
    memberDisplayNames,
    fmtTime,
    user,
    handleToggleEnabled,
    handleEditUser,
    userPwdModalRef,
    page,
    total,
    directTotal,
    directOnly,
    onDirectOnlyChange,
    handlePageChange,
    addOpen,
    deptId,
    departmentId,
    deptName,
    handleAdded,
    editMember,
    handleEditClose,
    handleEditSaved,
    toolbarActions,
  } = controller;
  const paginationLocale = usePaginationLocale();
  const selectLabels = useSelectLabels();
  const isArchivedMember = (member: DepartmentMember) =>
    isArchived || member.department?.status === "archived";
  const canEditMember = (member: DepartmentMember) =>
    !isArchivedMember(member) && member.enabled &&
    user?.user_id !== member.user_id && !member.roles.some(role => role.id === 1);
  const canResetPassword = user?.role === "admin";
  const memberTypeHeader = mrc.getThProps(2);
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div className="mb-4 flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h3 className="text-base font-semibold">
            {deptName}
            {isArchived && t("bs:department.archivedTag")}
          </h3>
          <Checkbox
            checked={directOnly}
            onCheckedChange={(checked) => onDirectOnlyChange?.(checked === true)}
            label={t("bs:organization.directMemberCount", { count: directTotal })}
          />
        </div>
        {(directAdmins.length > 0 || inheritedAdmins.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span>{t("bs:department.admins")}:</span>
            {directAdmins.map((admin) => (
              <Tag key={admin.user_id} size="small" color="default">
                {admin.user_name}
              </Tag>
            ))}
            {inheritedAdmins.map((admin) => (
              <SharedTooltip
                key={admin.user_id}
                content={t("bs:department.inheritedAdminSource", {
                  department: admin.sourceDeptName,
                })}
              >
                <span tabIndex={0}>
                  <Tag size="small" color="default">
                    {admin.user_name}
                  </Tag>
                </span>
              </SharedTooltip>
            ))}
          </div>
        )}
      </div>
      <div className="mb-4 flex shrink-0 flex-wrap items-center gap-2">
        <Select
          {...selectLabels}
          className="w-[140px]"
          aria-label={t("bs:department.memberType")}
          value={isPrimaryFilter}
          onChange={(value) =>
            setIsPrimaryFilter(value == null ? "all" : String(value))
          }
          options={[
            { value: "all", label: t("bs:organization.allRelations") },
            { value: "1", label: t("bs:department.primary") },
            { value: "0", label: t("bs:department.secondary") },
          ]}
        />
        <div className="flex-1" />
        {toolbarActions}
        <Button disabled={isArchived} onClick={() => setAddOpen(true)}>
          {t("bs:organization.addMember")}
        </Button>
      </div>
        <SharedTooltipProvider delayDuration={200}>
          <Table
            containerClassName="min-h-0 flex-1 scroll-pt-11"
            className="!w-auto min-w-full"
            style={{ tableLayout: "fixed", width: mrc.totalWidth }}
          >
            <TableHeader className="sticky top-0 z-10 bg-background">
              <TableRow>
                <TableHead {...mrc.getThProps(0)}>
                  {t("accountIdentity.nickname")}
                  <ColumnResizeHandle
                    columnIndex={0}
                    lastColumn={0 === memberLastCol}
                    startResize={mrc.startResize}
                  />
                </TableHead>
                <TableHead {...mrc.getThProps(1)}>
                  {t('accountIdentity.account')}
                  <ColumnResizeHandle columnIndex={1} lastColumn={1 === memberLastCol} startResize={mrc.startResize} />
                </TableHead>
                <TableHead
                  {...memberTypeHeader}
                  style={{ ...memberTypeHeader.style, minWidth: memberTypeHeader.style?.width }}
                >
                  {t("bs:department.memberType")}
                  <ColumnResizeHandle
                    columnIndex={2}
                    lastColumn={2 === memberLastCol}
                    startResize={mrc.startResize}
                  />
                </TableHead>
                <TableHead {...mrc.getThProps(3)}>
                  {t("bs:department.roles")}
                  <ColumnResizeHandle
                    columnIndex={3}
                    lastColumn={3 === memberLastCol}
                    startResize={mrc.startResize}
                  />
                </TableHead>
                <TableHead {...mrc.getThProps(4)}>
                  {t("bs:department.userGroups")}
                  <ColumnResizeHandle
                    columnIndex={4}
                    lastColumn={4 === memberLastCol}
                    startResize={mrc.startResize}
                  />
                </TableHead>
                <TableHead {...mrc.getThProps(5)}>
                  {t("bs:department.updateTime")}
                  <ColumnResizeHandle
                    columnIndex={5}
                    lastColumn={5 === memberLastCol}
                    startResize={mrc.startResize}
                  />
                </TableHead>
                <TableHead
                  style={mrc.getThProps(6).style}
                  className={cname(mrc.getThProps(6).className, "px-1.5")}
                >
                  {t("bs:department.enabled")}
                  <ColumnResizeHandle
                    columnIndex={6}
                    lastColumn={6 === memberLastCol}
                    startResize={mrc.startResize}
                  />
                </TableHead>
                <TableHead className="w-[1%] whitespace-nowrap">
                  {t("operations")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="py-8 text-center text-muted-foreground"
                  >
                    {t("loading")}
                  </TableCell>
                </TableRow>
              ) : members.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={8}
                    className="text-center text-muted-foreground"
                  >
                    {t("bs:department.noMembers")}
                  </TableCell>
                </TableRow>
              ) : (
                members.map((m) => (
                  <TableRow
                    key={`${m.department_id}:${m.user_id}`}
                    data-member-row={m.user_id}
                    data-member-department={m.department_id ?? departmentId}
                    onClick={event => {
                      const target = event.target;
                      if (!(target instanceof Element) || !event.currentTarget.contains(target)) return;
                      if (target.closest('button,a,input,textarea,select,[role="switch"],[role="checkbox"]')) return;
                      if (window.getSelection()?.toString()) return;
                      if (canEditMember(m)) handleEditUser(m);
                    }}
                    className={cname(
                      canEditMember(m) ? 'cursor-pointer' : '',
                      highlightUserId === m.user_id && (m.department_id ?? departmentId) === departmentId
                        ? "[&>td]:!bg-blue-50"
                        : ""
                    )}
                  >
                    <TableCell
                      {...mrc.getTdProps(0)}
                      title={memberDisplayNames.get(m.user_id) ?? m.user_name}
                    >
                      <span className="block truncate">{m.user_name}</span>
                    </TableCell>
                    <TableCell {...mrc.getTdProps(1)}>
                      {(() => {
                        const account = m.external_id === undefined ? m.person_id ?? '' : m.external_id ?? '';
                        return <div className="flex min-w-0 items-center gap-1">
                          <span className="min-w-0 flex-1 truncate" title={account}>{account || t('accountIdentity.noAccount')}</span>
                          {account && <SharedTooltip content={t('accountIdentity.copyAccount')}>
                            <Button type="button" size="small" variant="text" color="default" iconOnly
                              aria-label={t('accountIdentity.copyAccount')}
                              onClick={event => {
                                event.stopPropagation();
                                void copyText(account).then(() => toast.show({ type: 'success', message: t('accountIdentity.accountCopied') }))
                                  .catch(() => toast.show({ type: 'error', message: t('accountIdentity.copyFailed') }));
                              }}><Outlined.Copy aria-hidden /></Button>
                          </SharedTooltip>}
                        </div>;
                      })()}
                    </TableCell>
                    <TableCell {...mrc.getTdProps(2)}>
                      <div className="flex min-w-0 items-center gap-2">
                        <Tag
                          size="small"
                          color={m.is_primary === 1 ? "brand" : "default"}
                          className="shrink-0 whitespace-nowrap"
                        >
                          {m.is_primary === 1
                            ? t("bs:department.primary")
                            : t("bs:department.secondary")}
                        </Tag>
                        {m.department && (
                          <span className="min-w-0 truncate text-xs text-muted-foreground" title={m.department.name}>
                            {departmentDisplayName(m.department, t("bs:department.defaultOrganization"))}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell {...mrc.getTdProps(3)}>
                      <MemberRoleSummary member={m} />
                    </TableCell>
                    <TableCell {...mrc.getTdProps(4)}>
                      {(() => {
                        const text =
                          m.user_groups.map((g) => g.group_name).join(", ") ||
                          "-";
                        return (
                          <SharedTooltip content={text}>
                            <div className="cursor-default truncate">
                              {text}
                            </div>
                          </SharedTooltip>
                        );
                      })()}
                    </TableCell>
                    <TableCell
                      {...mrc.getTdProps(5)}
                      className="whitespace-nowrap text-muted-foreground"
                    >
                      {fmtTime(m.update_time ?? m.create_time)}
                    </TableCell>
                    <TableCell {...mrc.getTdProps(6)} className="px-1.5 text-right">
                      <Switch
                        checked={m.enabled}
                        disabled={
                          isArchivedMember(m) ||
                          (!m.enabled &&
                            !!m.disable_source &&
                            user?.role !== "admin")
                        }
                        onCheckedChange={(checked) =>
                          handleToggleEnabled(m, Boolean(checked))
                        }
                      />
                    </TableCell>
                    <TableCell className="w-[1%] whitespace-nowrap">
                      <Dropdown
                        align="end"
                        menu={
                          <>
                            <DropdownItem disabled={!canEditMember(m)} onSelect={() => handleEditUser(m)}>
                              {t("edit")}
                            </DropdownItem>
                            {canResetPassword && (
                              <DropdownItem
                                disabled={isArchivedMember(m)}
                                onSelect={() => userPwdModalRef.current?.open(m.user_id)}
                              >
                                {t("system.resetPwd")}
                              </DropdownItem>
                            )}
                          </>
                        }
                      >
                        <Button type="button" color="default" variant="text" iconOnly aria-label={`${t("more")} ${m.user_name}`}>
                          <Outlined.More aria-hidden />
                        </Button>
                      </Dropdown>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </SharedTooltipProvider>
      <div className="mt-4 flex min-h-8 shrink-0 justify-end">
        {!loading && (
          <Pagination
            locale={paginationLocale}
            current={page}
            pageSize={20}
            total={total}
            showTotal
            onChange={handlePageChange}
          />
        )}
      </div>
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
        deptId={editMember?.department?.dept_id ?? deptId}
        member={editMember}
        onClose={handleEditClose}
        onSaved={handleEditSaved}
      />
      <UserPwdModal ref={userPwdModalRef} />
    </div>
  );
}
