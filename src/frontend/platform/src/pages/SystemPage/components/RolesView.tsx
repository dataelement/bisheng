import { Button, Input, SearchInput } from '@bisheng/ui';
import { Switch } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";



import { TreeDepartmentSelect } from "@/components/bs-comp/department";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { ColumnResizeHandle } from "@/components/bs-ui/table/useResizableColumns";
import { cname } from "@/components/bs-ui/utils";
import {
  ADMIN_CHILD_MENUS,
  ADMIN_PARENT_ID,
  TASK_MODE_MENU_ID,
  WORKBENCH_CHILD_MENUS,
  WORKBENCH_PARENT_ID,
} from "./roleMenuSelection";
import { parseRoleQuota } from "./roleQuotaConfig";
import { RoleQuotaFields } from "./RoleQuotaFields";
import type { useRolesController } from "./Roles";
interface RolesViewProps {
  controller: ReturnType<typeof useRolesController>;
}
export function RolesView({ controller }: RolesViewProps) {
  const {
    requestCloseEditDialog,
    t,
    setKeyword,
    openCreate,
    rc,
    roleLastResizeColIndex,
    roles,
    scopeLabel,
    formatKnowledgeSpaceUploadQuota,
    formatChannelCreationLimit,
    formatSpaceCreationLimit,
    creatorLabel,
    fmtTime,
    openEdit,
    onDelete,
    page,
    total,
    setPage,
    loadRoles,
    keyword,
    editOpen,
    setEditOpen,
    activeRole,
    roleName,
    setRoleName,
    departmentId,
    setDepartmentId,
    isPlatformAdmin,
    quota,
    setQuota,
    isMenuLoading,
    menuLoadFailed,
    loadRoleMenus,
    workbenchApprovalMode,
    setWorkbenchApprovalMode,
    toggleMenuGroup,
    isMenuEnabled,
    renderWorkbenchChild,
    WORKBENCH_MENU_OPTIONS,
    toggleMenuItem,
    adminApprovalMode,
    setAdminApprovalMode,
    ADMIN_MENU_OPTIONS,
    isSaving,
    submitRole,
  } = controller;
  return (
    <div className="relative h-full">
      <div className="h-full overflow-y-auto pb-10 pt-2">
        <div className="mb-3 flex items-center justify-between">
          <div className="w-[220px]">
            <SearchInput placeholder={t("system.roleSearchPlaceholder")} onChange={(e) => setKeyword(e.target.value)} />
          </div>
          <Button className="flex justify-around" onClick={openCreate}>
            <Outlined.Plus className="size-4 shrink-0" />
            <span className="mx-4 text-[#fff]">{t("create")}</span>
          </Button>
        </div>
        <Table noScroll className="mb-6 !w-auto min-w-full" style={{ tableLayout: "fixed", width: rc.totalWidth }}>
          <TableHeader>
            <TableRow>
              <TableHead {...rc.getThProps(0)}>
                {t("system.roleName")}
                <ColumnResizeHandle
                  columnIndex={0}
                  lastColumn={0 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(1)}>
                {t("system.roleScope")}
                <ColumnResizeHandle
                  columnIndex={1}
                  lastColumn={1 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(2)}>
                {t("system.roleListKnowledgeSpaceUploadLimit")}
                <ColumnResizeHandle
                  columnIndex={2}
                  lastColumn={2 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(3)}>
                {t("system.channelQuotaLimit")}
                <ColumnResizeHandle
                  columnIndex={3}
                  lastColumn={3 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(4)}>
                {t("system.spaceCreateQuotaLimit")}
                <ColumnResizeHandle
                  columnIndex={4}
                  lastColumn={4 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(5)}>
                {t("system.userCount")}
                <ColumnResizeHandle
                  columnIndex={5}
                  lastColumn={5 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(6)}>
                {t("system.creator")}
                <ColumnResizeHandle
                  columnIndex={6}
                  lastColumn={6 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(7)}>
                {t("createTime")}
                <ColumnResizeHandle
                  columnIndex={7}
                  lastColumn={7 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead {...rc.getThProps(8)}>
                {t("system.changeTime")}
                <ColumnResizeHandle
                  columnIndex={8}
                  lastColumn={8 === roleLastResizeColIndex}
                  startResize={rc.startResize}
                />
              </TableHead>
              <TableHead style={rc.getThProps(9).style} className={cname(rc.getThProps(9).className, "text-right")}>
                {t("operations")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {roles.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="text-center text-gray-400">
                  {t("build.empty")}
                </TableCell>
              </TableRow>
            ) : (
              roles.map((el) => (
                <TableRow key={el.id}>
                  <TableCell {...rc.getTdProps(0)} className="font-medium">
                    {el.role_name}
                  </TableCell>
                  <TableCell {...rc.getTdProps(1)} className="whitespace-normal break-words text-left">
                    {scopeLabel(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(2)} className="whitespace-nowrap tabular-nums">
                    {formatKnowledgeSpaceUploadQuota(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(3)} className="whitespace-nowrap tabular-nums">
                    {formatChannelCreationLimit(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(4)} className="whitespace-nowrap tabular-nums">
                    {formatSpaceCreationLimit(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(5)}>{el.user_count ?? "-"}</TableCell>
                  <TableCell
                    {...rc.getTdProps(6)}
                    className={cname(
                      "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-sm text-muted-foreground",
                    )}
                    title={creatorLabel(el)}
                  >
                    {creatorLabel(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(7)} className="whitespace-nowrap tabular-nums">
                    {fmtTime(el.create_time)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(8)} className="whitespace-nowrap tabular-nums">
                    {fmtTime(el.update_time)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(9)} className="text-right">
                    {el.is_readonly ? (
                      <span className="text-sm text-muted-foreground">&mdash;</span>
                    ) : (
                      <>
                        <Button variant="link" className="px-0 pl-4" onClick={() => openEdit(el)}>
                          {t("edit")}
                        </Button>
                        <Button variant="link" disabled={[1, 2].includes(el.id)} className="px-0 pl-4 text-red-500" onClick={() => onDelete(el)}>
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
            setPage(p);
            loadRoles(p, keyword);
          }}
        />
      </div>

      <Dialog
        open={editOpen}
        onOpenChange={(open) => {
          if (open) {
            setEditOpen(true);
          } else {
            requestCloseEditDialog();
          }
        }}
      >
        <DialogContent className="flex max-h-[85vh] max-w-2xl flex-col sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{activeRole ? t("system.roleEditTitle") : t("system.roleCreateTitle")}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            <div>
              <Label>{t("system.roleName")}</Label>
              <Input value={roleName} onChange={(e) => setRoleName(e.target.value)} maxLength={128} placeholder={t("system.roleNameInputPlaceholder")} className={"mt-1"} showCount />
            </div>

            <div>
              <Label>{t("system.roleScope")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("system.roleScopeHint")}</p>
              <TreeDepartmentSelect
                modal={false}
                className="mt-1"
                value={departmentId === "none" ? null : Number(departmentId)}
                onChange={(id) => setDepartmentId(id == null ? "none" : String(id))}
                allowNone={isPlatformAdmin}
                noneLabel={t("system.scopeGlobalRole")}
                placeholder={t("system.treeDepartmentSelectPlaceholder")}
                emptyText={t("system.treeDepartmentSelectEmpty")}
              />
            </div>

            <RoleQuotaFields value={quota} onChange={setQuota} />

            <div className="rounded-md border p-3">
              <Label>{t("system.menuPermissionSection")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("system.menuPermissionHint")}</p>
              {isMenuLoading && <p className="mt-2 text-xs text-muted-foreground">{t("system.roleMenuLoading")}</p>}
              {menuLoadFailed && activeRole && (
                <div className="mt-2 flex items-center gap-3 text-xs text-destructive">
                  <span>{t("system.roleMenuLoadFailed")}</span>
                  <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={() => void loadRoleMenus(activeRole, parseRoleQuota(activeRole.quota_config))}>
                    {t("retry")}
                  </Button>
                </div>
              )}
              <div className="mt-3 space-y-4">
                <div className="rounded-md border bg-muted/20 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-xs font-medium text-muted-foreground">
                      {t("system.workbenchMenuAuthorization")}
                    </div>
                  </div>
                  <label className="mb-3 flex cursor-pointer items-center gap-2 rounded-md border bg-background px-3 py-2">
                    <Switch
                      checked={workbenchApprovalMode}
                      onCheckedChange={(v) => setWorkbenchApprovalMode(Boolean(v))}
                      disabled={isMenuLoading || (Boolean(activeRole) && menuLoadFailed)}
                    />
                    <div>
                      <div className="text-sm font-medium">{t("system.menuApprovalMode")}</div>
                      <div className="text-xs text-muted-foreground">{t("system.menuApprovalModeWorkbenchHint")}</div>
                    </div>
                  </label>
                  <label
                    className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-background px-2 py-1 text-base font-semibold"
                    onClick={() =>
                      toggleMenuGroup(WORKBENCH_PARENT_ID, WORKBENCH_CHILD_MENUS, !isMenuEnabled(WORKBENCH_PARENT_ID))
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

                  <div className="mt-3 flex flex-col gap-2">
                    {renderWorkbenchChild(WORKBENCH_MENU_OPTIONS.find((m) => m.id === "home")!)}


                    <div className="ml-6 border-l border-border pl-3">
                      <label
                        className={`inline-flex w-fit items-center gap-1.5 rounded-md bg-background px-2 py-1.5 text-sm ${
                          !isMenuEnabled(WORKBENCH_PARENT_ID) || !isMenuEnabled("home")
                            ? "cursor-not-allowed opacity-50"
                            : "cursor-pointer"
                        }`}
                        onClick={() =>
                          isMenuEnabled(WORKBENCH_PARENT_ID) &&
                          isMenuEnabled("home") &&
                          toggleMenuItem(
                            WORKBENCH_PARENT_ID,
                            WORKBENCH_CHILD_MENUS,
                            TASK_MODE_MENU_ID,
                            !isMenuEnabled(TASK_MODE_MENU_ID),
                          )
                        }
                      >
                        <Switch
                          checked={isMenuEnabled(TASK_MODE_MENU_ID)}
                          disabled={!isMenuEnabled(WORKBENCH_PARENT_ID) || !isMenuEnabled("home")}
                          onCheckedChange={(checked) =>
                            toggleMenuItem(WORKBENCH_PARENT_ID, WORKBENCH_CHILD_MENUS, TASK_MODE_MENU_ID, checked)
                          }
                          onClick={(e) => e.stopPropagation()}
                        />
                        <span>{t("menu.linsightTaskMode")}</span>
                      </label>
                      <p className="mt-1 pl-2 text-xs text-muted-foreground">{t("system.workbenchTaskModeHint")}</p>
                    </div>


                    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                      {WORKBENCH_MENU_OPTIONS.filter((m) => m.id !== "home").map(renderWorkbenchChild)}
                    </div>
                  </div>
                </div>

                <div className="rounded-md border bg-muted/20 p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-xs font-medium text-muted-foreground">
                      {t("system.adminMenuAuthorization")}
                    </div>
                  </div>
                  <label className="mb-3 flex cursor-pointer items-center gap-2 rounded-md border bg-background px-3 py-2">
                    <Switch
                      checked={adminApprovalMode}
                      onCheckedChange={(v) => setAdminApprovalMode(Boolean(v))}
                      disabled={isMenuLoading || (Boolean(activeRole) && menuLoadFailed)}
                    />
                    <div>
                      <div className="text-sm font-medium">{t("system.menuApprovalMode")}</div>
                      <div className="text-xs text-muted-foreground">{t("system.menuApprovalModeAdminHint")}</div>
                    </div>
                  </label>
                  <label
                    className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-background px-2 py-1 text-base font-semibold"
                    onClick={() => toggleMenuGroup(ADMIN_PARENT_ID, ADMIN_CHILD_MENUS, !isMenuEnabled(ADMIN_PARENT_ID))}
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
                      (m) => !("parentMenuId" in m) || !m.parentMenuId || isMenuEnabled(m.parentMenuId),
                    ).map((m) => (
                      <label
                        key={m.id}
                        className={`inline-flex items-center gap-1.5 rounded-md bg-background px-2 py-1.5 text-sm ${
                          !isMenuEnabled(ADMIN_PARENT_ID) ? "cursor-not-allowed opacity-50" : "cursor-pointer"
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
            <Button variant="outlined" onClick={requestCloseEditDialog} disabled={isSaving} color="default">
              {t("cancel")}
            </Button>
            <Button onClick={submitRole} disabled={isSaving || isMenuLoading || menuLoadFailed}>
              {isSaving ? `${t("save")}...` : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
