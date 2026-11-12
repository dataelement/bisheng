import {
  Button,
  Pagination,
  Select,
  SearchInput,
  Switch,
  Tag,
  Tooltip as SharedTooltip,
  TooltipProvider as SharedTooltipProvider,
  toast,
} from "@bisheng/ui";
import { Outlined } from 'bisheng-icons';
import { copyText } from '@/utils';
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
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
    memberSearch,
    setMemberSearch,
    handleMemberSearch,
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
    handlePageChange,
    addOpen,
    deptId,
    deptName,
    handleAdded,
    editMember,
    handleEditClose,
    handleEditSaved,
    toolbarActions,
  } = controller;
  const paginationLocale = usePaginationLocale();
  const selectLabels = useSelectLabels();
  return (
    <div className="min-w-0">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base font-semibold">
          {deptName}
          {isArchived && t("bs:department.archivedTag")}
        </h3>
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
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SearchInput size="medium" className="w-[220px]" value={memberSearch ?? ''}
          aria-label={t('accountIdentity.search')} placeholder={t('accountIdentity.search')}
          clearLabel={t('sharedUi.clear')} onChange={event => setMemberSearch(event.target.value)}
          onSearch={handleMemberSearch} onClear={() => handleMemberSearch('')} />
        <span className="rounded-md border px-3 py-1.5 text-sm">
          {t("bs:organization.directMemberCount", { count: total })}
        </span>
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
      <div className="overflow-x-auto">
        <SharedTooltipProvider delayDuration={200}>
          <Table
            noScroll
            className="!w-auto min-w-full"
            style={{ tableLayout: "fixed", width: mrc.totalWidth }}
          >
            <TableHeader>
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
                <TableHead {...mrc.getThProps(2)}>
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
                <TableHead {...mrc.getThProps(6)}>
                  {t("bs:department.enabled")}
                  <ColumnResizeHandle
                    columnIndex={6}
                    lastColumn={6 === memberLastCol}
                    startResize={mrc.startResize}
                  />
                </TableHead>
                <TableHead
                  style={mrc.getThProps(7).style}
                  className={cname(mrc.getThProps(7).className, "text-right")}
                >
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
                    key={m.user_id}
                    data-member-row={m.user_id}
                    onClick={event => {
                      const target = event.target;
                      if (target instanceof Element && target.closest('button,a,input,textarea,select,[role="switch"],[role="checkbox"]')) return;
                      if (window.getSelection()?.toString()) return;
                      if (!isArchived && m.enabled && user?.user_id !== m.user_id && !m.roles.some(role => role.id === 1)) handleEditUser(m);
                    }}
                    className={cname(
                      !isArchived && m.enabled && user?.user_id !== m.user_id && !m.roles.some(role => role.id === 1) ? 'cursor-pointer' : '',
                      highlightUserId != null && m.user_id === highlightUserId
                        ? "bg-primary/10"
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
                      <Tag
                        size="small"
                        color={m.is_primary === 1 ? "brand" : "default"}
                      >
                        {m.is_primary === 1
                          ? t("bs:department.primary")
                          : t("bs:department.secondary")}
                      </Tag>
                    </TableCell>
                    <TableCell {...mrc.getTdProps(3)}>
                      {(() => {
                        const roleNames: string[] = [];
                        if (m.is_department_admin) {
                          roleNames.push(t("bs:department.deptAdminRoleName"));
                        }
                        roleNames.push(...m.roles.map((r) => r.role_name));
                        const text = roleNames.join(", ") || "-";
                        return (
                          <SharedTooltip content={text}>
                            <div className="cursor-default truncate">
                              {text}
                            </div>
                          </SharedTooltip>
                        );
                      })()}
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
                    <TableCell {...mrc.getTdProps(6)}>
                      <Switch
                        checked={m.enabled}
                        disabled={
                          isArchived ||
                          (!m.enabled &&
                            !!m.disable_source &&
                            user?.role !== "admin")
                        }
                        onCheckedChange={(checked) =>
                          handleToggleEnabled(m, Boolean(checked))
                        }
                      />
                    </TableCell>
                    <TableCell {...mrc.getTdProps(7)} className="text-right">
                      {(() => {
                        const isSuperAdmin = m.roles.some(
                          (role) => role.id === 1
                        );
                        const canResetPwd = user.role === "admin";
                        return (
                          <div className="flex flex-wrap items-center justify-end gap-x-2">
                            {isSuperAdmin ? (
                              <Button variant="link" size="small" disabled>
                                {t("edit")}
                              </Button>
                            ) : (
                              <Button
                                variant="link"
                                size="small"
                                disabled={
                                  isArchived ||
                                  user.user_id === m.user_id ||
                                  !m.enabled
                                }
                                onClick={() => handleEditUser(m)}
                              >
                                {t("edit")}
                              </Button>
                            )}
                            {canResetPwd && (
                              <Button
                                variant="link"
                                size="small"
                                disabled={isArchived}
                                onClick={() =>
                                  !isArchived &&
                                  userPwdModalRef.current?.open(m.user_id)
                                }
                              >
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
        </SharedTooltipProvider>
      </div>
      {!loading && (
        <div className="mt-4 flex justify-end">
          <Pagination
            locale={paginationLocale}
            current={page}
            pageSize={20}
            total={total}
            showTotal
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
  );
}
