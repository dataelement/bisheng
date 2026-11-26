import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { Button, Checkbox, Input, Pagination, SearchInput, Select, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { createPortal } from "react-dom";

import { TreeDepartmentSelect } from "@/components/bs-comp/department";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { Label } from "@/components/bs-ui/label";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
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

type RoleMenuOption = {
  id: string;
  labelKey: string;
  hintKey?: string;
  children?: readonly RoleMenuOption[];
};

const WORKBENCH_MENU_OPTIONS: readonly RoleMenuOption[] = [
  {
    id: "home",
    labelKey: "menu.workbenchHome",
    children: [{ id: TASK_MODE_MENU_ID, labelKey: "menu.linsightTaskMode", hintKey: "system.workbenchTaskModeHint" }],
  },
  { id: "apps", labelKey: "menu.workbenchApps" },
  { id: "subscription", labelKey: "menu.workbench1" },
  { id: "knowledge_space", labelKey: "menu.workbench2" },
];

const ADMIN_MENU_OPTIONS: readonly RoleMenuOption[] = [
  { id: "board", labelKey: "menu.board" },
  { id: "build", labelKey: "menu.skills", children: [{ id: "create_app", labelKey: "menu.createApp" }] },
  {
    id: "knowledge",
    labelKey: "menu.workbench2",
    children: [{ id: "create_knowledge", labelKey: "menu.createKnowledge" }],
  },
  { id: "dataset", labelKey: "menu.dataset" },
  { id: "model", labelKey: "menu.models" },
  { id: "evaluation", labelKey: "menu.evaluation" },
  { id: "mark_task", labelKey: "menu.annotation" },
  { id: "log", labelKey: "menu.log" },
];

interface RoleMenuSectionProps {
  titleKey: string;
  entryKey: string;
  entryHintKey: string;
  approvalHintKey: string;
  approvalEnabled: boolean;
  onApprovalChange: (value: boolean) => void;
  parentId: string;
  childIds: readonly string[];
  options: readonly RoleMenuOption[];
  controlsDisabled: boolean;
  hideInactiveChildren?: boolean;
  controller: Pick<ReturnType<typeof useRolesController>, "t" | "isMenuEnabled" | "toggleMenuGroup" | "toggleMenuItem">;
}

function MenuHint({ text }: { text: string }) {
  return (
    <Tooltip content={text}>
      <Button type="button" variant="text" color="default" size="small" iconOnly aria-label={text}>
        <Outlined.Question aria-hidden="true" size={14} className="text-text-3" />
      </Button>
    </Tooltip>
  );
}

function RoleMenuSection({
  titleKey, entryKey, entryHintKey, approvalHintKey, approvalEnabled, onApprovalChange,
  parentId, childIds, options, controlsDisabled, hideInactiveChildren, controller,
}: RoleMenuSectionProps) {
  const { t, isMenuEnabled, toggleMenuGroup, toggleMenuItem } = controller;
  const isAreaEnabled = isMenuEnabled(parentId);

  const renderMenuOption = (option: RoleMenuOption, disabled: boolean) => (
    <div className="flex min-w-0 items-center gap-1">
      <Checkbox
        label={t(option.labelKey).replace(/\u2002+/g, "")}
        checked={isMenuEnabled(option.id)}
        disabled={disabled}
        onCheckedChange={(checked) => toggleMenuItem(parentId, childIds, option.id, checked === true)}
      />
      {option.hintKey && <MenuHint text={t(option.hintKey)} />}
    </div>
  );

  return (
    <fieldset className="min-w-0 overflow-hidden rounded-xl border border-border-base" aria-label={t(titleKey)}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border-base px-4 py-2">
        <h4 className="text-body font-medium text-text-1">{t(titleKey)}</h4>
        <div className="flex items-center gap-1">
          <Checkbox
            label={t("system.menuApprovalMode")}
            checked={approvalEnabled}
            disabled={controlsDisabled}
            onCheckedChange={(checked) => onApprovalChange(checked === true)}
          />
          <MenuHint text={t(approvalHintKey)} />
        </div>
      </div>

      <div className="space-y-3 px-4 pt-4">
        <Checkbox
          label={<span className="font-medium">{t(entryKey)}</span>}
          description={t(entryHintKey)}
          checked={isAreaEnabled}
          disabled={controlsDisabled}
          onCheckedChange={(checked) => toggleMenuGroup(parentId, childIds, checked === true)}
        />
        <ul className="-mx-4 rounded-none">
          {options.map((option) => {
            const optionEnabled = isMenuEnabled(option.id);
            return (
              <li key={option.id} className="grid min-h-11 items-start gap-x-6 gap-y-1 bg-bg-page px-4 py-2 odd:bg-fill-1/60 sm:grid-cols-[minmax(8rem,1fr)_minmax(0,2fr)]">
                {renderMenuOption(option, controlsDisabled || !isAreaEnabled)}
                {option.children && (!hideInactiveChildren || optionEnabled) && (
                  <ul className="ml-3 space-y-1 border-l border-border-base pl-3 sm:ml-0">
                    {option.children.map((child) => (
                      <li key={child.id}>{renderMenuOption(child, controlsDisabled || !isAreaEnabled || !optionEnabled)}</li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </fieldset>
  );
}

interface RolesViewProps {
  controller: ReturnType<typeof useRolesController>;
  headerTarget?: HTMLDivElement | null;
}
export function RolesView({ controller, headerTarget }: RolesViewProps) {
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
    roleType,
    setRoleType,
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
    adminApprovalMode,
    setAdminApprovalMode,
    isSaving,
    submitRole,
  } = controller;
  const paginationLocale = usePaginationLocale();
  const selectLabels = useSelectLabels();
  const userRolesTitle = t("catalog.menuRoles", { ns: "permission" });
  const menuControlsDisabled = isMenuLoading || menuLoadFailed;
  const header = (
    <>
      <div className="flex min-w-0 items-center justify-end gap-3">
        <SearchInput
          className="w-full min-w-0 sm:w-60"
          aria-label={t("system.roleSearchPlaceholder")}
          placeholder={t("system.roleSearchPlaceholder")}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <Button className="shrink-0" onClick={openCreate}>{t("system.roleCreateTitle")}</Button>
      </div>
      <p className="text-body text-text-2">{t("system.userRolesDescription")}</p>
    </>
  );
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {headerTarget ? createPortal(header, headerTarget) : headerTarget === undefined ? header : null}
        <Table
          aria-label={userRolesTitle}
          className="!w-auto min-w-full border-collapse border-spacing-0 text-body text-text-1"
          containerClassName="min-h-0 flex-1 rounded-lg"
          style={{ tableLayout: "fixed", width: rc.totalWidth }}
        >
          <TableHeader className="sticky top-0 z-10 bg-fill-1 [&_th]:h-11 [&_th]:px-3 [&_th]:py-2 [&_th]:text-text-2">
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
              <TableRow hoverable={false}>
                <TableCell colSpan={10} className="h-14 !rounded-none !bg-bg-page text-center text-text-3">
                  {t("build.empty")}
                </TableCell>
              </TableRow>
            ) : (
              roles.map((el) => (
                <TableRow key={el.id} hoverable={false} className="bg-bg-page even:bg-fill-1/60 [&_td]:h-14 [&_td]:!rounded-none [&_td]:!bg-transparent [&_td]:px-3">
                  <TableCell {...rc.getTdProps(0)} className="break-words font-medium">
                    {el.role_name}
                    <div className="text-caption text-text-3">
                      {t(el.role_type === "global" ? "system.roleTypeShared" : "system.roleTypeTenant")}
                      {el.tenant_id != null && ` · ${t("system.roleOwner", { id: el.tenant_id })}`}
                    </div>
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
                      "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-text-3",
                    )}
                    title={creatorLabel(el)}
                  >
                    {creatorLabel(el)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(7)} className="whitespace-nowrap text-caption tabular-nums">
                    {fmtTime(el.create_time)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(8)} className="whitespace-nowrap text-caption tabular-nums">
                    {fmtTime(el.update_time)}
                  </TableCell>
                  <TableCell {...rc.getTdProps(9)} className="text-right">
                    {el.is_readonly ? (
                      <span className="text-text-3">&mdash;</span>
                    ) : (
                      <div className="flex justify-end gap-2">
                        <Button size="small" variant="link" onClick={() => openEdit(el)}>
                          {t("edit")}
                        </Button>
                        <Button size="small" variant="link" color="danger" disabled={[1, 2].includes(el.id)} onClick={() => onDelete(el)}>
                          {t("delete")}
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        <Pagination locale={paginationLocale}
          className="m-0 w-auto justify-end"
          current={page}
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
        <DialogContent
          aria-describedby={undefined}
          className="flex max-h-[85dvh] w-[calc(100%-2rem)] max-w-3xl flex-col border-border-base bg-bg-page text-text-1 dark:bg-bg-page"
        >
          <DialogHeader>
            <DialogTitle className="text-h4 text-text-1">{activeRole ? t("system.roleEditTitle") : t("system.roleCreateTitle")}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
            <div>
              <Label htmlFor="role-name">{t("system.roleName")}</Label>
              <Input id="role-name" value={roleName} onChange={(e) => setRoleName(e.target.value)} maxLength={128} placeholder={t("system.roleNameInputPlaceholder")} className={"mt-1"} showCount />
            </div>

            <div>
              <Label>{t("system.roleType")}</Label>
              {!activeRole && isPlatformAdmin ? (
                <Select
                  {...selectLabels}
                  aria-label={t("system.roleType")}
                  className="mt-1"
                  value={roleType}
                  options={[
                    { value: "tenant", label: t("system.roleTypeTenant") },
                    { value: "global", label: t("system.roleTypeShared") },
                  ]}
                  onChange={(value) => setRoleType(value === "global" ? "global" : "tenant")}
                />
              ) : (
                <p className="mt-1 text-sm">{t(activeRole?.role_type === "global" ? "system.roleTypeShared" : "system.roleTypeTenant")}</p>
              )}
              <p className="mt-1 text-caption text-text-3">{t("system.roleTypeHint")}</p>
            </div>

            <div>
              <Label>{t("system.roleScope")}</Label>
              <p className="mt-1 text-caption text-text-3">{t("system.roleScopeHint")}</p>
              <TreeDepartmentSelect
                modal={false}
                className="mt-1"
                value={departmentId === "none" ? null : Number(departmentId)}
                onChange={(id) => setDepartmentId(id == null ? "none" : String(id))}
                allowNone={isPlatformAdmin}
                noneLabel={t("system.scopeAllDepartments")}
                placeholder={t("system.treeDepartmentSelectPlaceholder")}
                emptyText={t("system.treeDepartmentSelectEmpty")}
              />
            </div>

            <RoleQuotaFields value={quota} onChange={setQuota} />

            <section className="space-y-4" aria-label={t("system.menuPermissionSection")}>
              <h3 className="text-h4 text-text-1">{t("system.menuPermissionSection")}</h3>
              {isMenuLoading && (
                <LoadingState size="panel" label={t("system.roleMenuLoading")} className="text-caption text-text-3" />
              )}
              {menuLoadFailed && activeRole && (
                <div className="flex items-center gap-3 text-caption text-danger">
                  <span>{t("system.roleMenuLoadFailed")}</span>
                  <Button
                    type="button"
                    variant="link"
                    size="small"
                    onClick={() => void loadRoleMenus(activeRole, parseRoleQuota(activeRole.quota_config))}
                  >
                    {t("retry")}
                  </Button>
                </div>
              )}
              <RoleMenuSection
                titleKey="system.workbenchMenuAuthorization"
                entryKey="menu.workspace"
                entryHintKey="system.workbenchMenuEntryHint"
                approvalHintKey="system.menuApprovalModeWorkbenchHint"
                approvalEnabled={workbenchApprovalMode}
                onApprovalChange={setWorkbenchApprovalMode}
                parentId={WORKBENCH_PARENT_ID}
                childIds={WORKBENCH_CHILD_MENUS}
                options={WORKBENCH_MENU_OPTIONS}
                controlsDisabled={menuControlsDisabled}
                controller={controller}
              />
              <RoleMenuSection
                titleKey="system.adminMenuAuthorization"
                entryKey="system.adminSpace"
                entryHintKey="system.adminMenuEntryHint"
                approvalHintKey="system.menuApprovalModeAdminHint"
                approvalEnabled={adminApprovalMode}
                onApprovalChange={setAdminApprovalMode}
                parentId={ADMIN_PARENT_ID}
                childIds={ADMIN_CHILD_MENUS}
                options={ADMIN_MENU_OPTIONS}
                controlsDisabled={menuControlsDisabled}
                hideInactiveChildren
                controller={controller}
              />
            </section>
          </div>
          <DialogFooter className="shrink-0 pt-3">
            <Button variant="outlined" onClick={requestCloseEditDialog} disabled={isSaving} color="default">
              {t("cancel")}
            </Button>
            <Button onClick={submitRole} loading={isSaving} disabled={isSaving || menuControlsDisabled}>
              {t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
