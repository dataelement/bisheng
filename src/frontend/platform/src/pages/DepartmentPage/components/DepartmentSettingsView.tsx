import { Alert, Button, Input, Select, notification } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { Checkbox, Tooltip as SharedTooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { TreeDepartmentSelect } from "@/components/bs-comp/department/TreeDepartmentSelect";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import DepartmentUsersSelect, {
  DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect";

import { Label } from "@/components/bs-ui/label";
import { Separator } from "@/components/bs-ui/separator";

import { unmountTenantApi } from "@/controllers/API/department";
import { handleUiRequest } from "@/controllers/request";
import { isGuestDepartmentDeptId } from "@/pages/DepartmentPage/constants/systemDepartments";

import type { useDepartmentSettingsController } from "./DepartmentSettings";
interface DepartmentSettingsViewProps {
  controller: ReturnType<typeof useDepartmentSettingsController>;
}
export function DepartmentSettingsView({ controller }: DepartmentSettingsViewProps) {
  const {
    FORM_CONTROL_WIDTH,
    handleRestore,
    isArchived,
    t,
    loading,
    isSynced,
    name,
    setName,
    isRootDept,
    canEditParent,
    parentIdValue,
    setParentIdValue,
    dept,
    parentDisplayName,
    canEditPermissions,
    adminSelectValue,
    setAdminSelectValue,
    adminSelectValueRef,
    defaultRoleIds,
    assignableRoles,
    setDefaultRoleIds,
    applyDefaultRolesToExisting,
    setApplyDefaultRolesToExisting,
    handlePurge,
    handleGlobalSave,
    saving,
    onMarkAsTenant,
    onChanged,
    handleDelete,
  } = controller;
  const selectLabels = useSelectLabels();
  return (
    <div className="max-w-3xl pb-8">
      {isArchived && (
        <Alert
          type="warning"
          className="mb-4"
          description={t("bs:department.archivedNotice")}
        />
      )}

      {loading && <p className="mb-4 text-sm text-muted-foreground">{t("loading", { ns: "bs" })}</p>}


      <section className="space-y-4">
        <div>
          <h3 className="mb-2 text-base font-semibold tracking-tight text-foreground">
            {t("bs:department.sectionBasic")}
          </h3>
          <Separator />
        </div>
        <div className="space-y-1.5">
          <Label>{t("bs:department.name")}</Label>
          {isSynced || isArchived ? (
            <Input value={name} disabled className={FORM_CONTROL_WIDTH} />
          ) : (
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={50} className={FORM_CONTROL_WIDTH} showCount />
          )}
        </div>
        {!isRootDept && (
          <div className="space-y-1.5">
            <Label>{t("bs:department.parentDept")}</Label>
            {canEditParent ? (
              <TreeDepartmentSelect
                value={parentIdValue}
                onChange={(id) => setParentIdValue(id)}
                excludeSubtreePath={dept.path}
                className={FORM_CONTROL_WIDTH}
                placeholder={t("bs:department.selectDept")}
                searchPlaceholder={t("bs:department.parentDept")}
                modal={false}
              />
            ) : (
              <Input value={parentDisplayName} disabled className={FORM_CONTROL_WIDTH} />
            )}
          </div>
        )}
      </section>


      {!isArchived && (
        <section className="mt-6 space-y-4">
          <div>
            <h3 className="mb-2 text-base font-semibold tracking-tight text-foreground">
              {t("bs:department.sectionPermissions")}
            </h3>
            <Separator />
          </div>
          <div className="space-y-1.5">
            <Label>{t("bs:department.admins")}</Label>
            <DepartmentUsersSelect
              multiple
              disabled={!canEditPermissions}
              value={adminSelectValue}
              onChange={(vals) => {
                const v = (vals as DepartmentUserOption[]) || [];
                setAdminSelectValue(v);
                adminSelectValueRef.current = v;
              }}
              placeholder={t("bs:department.adminSelectPlaceholder")}
              searchPlaceholder={t("bs:department.searchUsersPlaceholder")}
              className={FORM_CONTROL_WIDTH}
              // Tenant-root depts: admin assignment writes the FGA
              // ``admin tenant:X`` tuple, so we constrain the picker to the
              // dept's own subtree. Plain depts keep the full org tree.
              rootDeptId={dept.is_tenant_root ? dept.id : undefined}
              emptyMessage={dept.is_tenant_root ? t("bs:tenant.initialAdminEmptySubtree") : undefined}
            />
            {dept.is_tenant_root ? (
              <p className="mt-1 max-w-md text-xs leading-snug text-gray-500 dark:text-gray-400">
                {t("bs:tenant.initialAdminSubtreeHint")}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label>{t("bs:department.defaultRoles")}</Label>
            <Select
              {...selectLabels}
              multiple
              showSearch
              aria-label={t("bs:department.defaultRoles")}
              value={defaultRoleIds}
              options={assignableRoles.filter((o) => o.value != null && o.value !== "")}
              placeholder={t("bs:department.selectRoles")}
              onChange={(vals) => setDefaultRoleIds(vals.map(String))}
              disabled={!canEditPermissions}
              className={FORM_CONTROL_WIDTH}
            />
            <label className="mt-2 flex max-w-md cursor-pointer items-start gap-2 text-sm leading-snug">
              <Checkbox
                className="mt-0.5"
                checked={applyDefaultRolesToExisting}
                disabled={!canEditPermissions}
                onCheckedChange={(v) => setApplyDefaultRolesToExisting(Boolean(v))}
              />
              <span className="flex flex-1 flex-wrap items-center gap-1.5 text-foreground">
                {t("bs:department.applyDefaultRolesToExisting")}
                <span
                  className="inline-flex shrink-0"
                  onClick={(e) => e.preventDefault()}
                  onPointerDown={(e) => e.stopPropagation()}
                >
                  <SharedTooltip content={t("bs:department.applyDefaultRolesToExistingTooltip")}>
                    <span tabIndex={0} className="text-muted-foreground hover:text-foreground">
                      <Outlined.Question className="size-3.5 shrink-0" />
                    </span>
                  </SharedTooltip>
                </span>
              </span>
            </label>
            <p className="mt-1 max-w-md text-xs leading-snug text-gray-500 dark:text-gray-400">
              {t("bs:department.defaultRolesHint")}
            </p>
          </div>
        </section>
      )}


      {isArchived && (
        <div className="mt-5 border-t pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outlined" onClick={handleRestore} color="default">
              {t("bs:department.restore")}
            </Button>
            {!isGuestDepartmentDeptId(dept.dept_id) ? (
              <Button variant="solid" onClick={handlePurge} color="danger">
                {t("bs:department.permanentDelete")}
              </Button>
            ) : null}
          </div>
        </div>
      )}


      {!isArchived && (
        <div className="mt-5 border-t pt-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {canEditPermissions && (
                <Button type="button" onClick={handleUiRequest(handleGlobalSave)} disabled={saving}>
                  {t("save")}
                </Button>
              )}
            </div>
            <div className="min-w-[1rem] flex-1" />
            {onMarkAsTenant && !isRootDept && !dept.is_tenant_root && (
              <Button variant="outlined" onClick={() => onMarkAsTenant(dept.id, dept.name)} className="shrink-0" color="default">
                <Outlined.City className="mr-1.5 h-4 w-4" />
                {t("bs:tenant.markAsTenant")}
              </Button>
            )}
            {onMarkAsTenant && !isRootDept && dept.is_tenant_root && (
              <Button variant="outlined" onClick={() => {
                  bsConfirm({
                    title: t("bs:tenant.unmountTitle"),
                    desc: t("bs:tenant.unmountConfirm"),
                    okTxt: t("bs:tenant.unmountOk"),
                    onOk(next) {
                      return unmountTenantApi(dept.id).then((res) => {
                        if (res) {
                          notification.open({ type: "success", title: String(t("bs:tenant.unmountSuccess") ?? ''), description: "" });
                          onChanged();
                        }
                        next();
                      });
                    },
                  });
                }} className="shrink-0" color="default">
                <Outlined.City className="mr-1.5 h-4 w-4" />
                {t("bs:tenant.unmount")}
              </Button>
            )}
            {!isSynced && dept.parent_id !== null && !isGuestDepartmentDeptId(dept.dept_id) && (
              <Button variant="solid" onClick={handleDelete} className="shrink-0" color="danger">
                {t("bs:department.delete")}
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
