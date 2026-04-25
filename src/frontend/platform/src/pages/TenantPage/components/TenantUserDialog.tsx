import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
import DepartmentUsersSelect, {
  type DepartmentUserOption,
} from "@/components/bs-comp/selectComponent/DepartmentUsersSelect";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table";
import { toast } from "@/components/bs-ui/toast/use-toast";
import {
  addTenantUsersApi,
  getTenantApi,
  getTenantUsersApi,
  grantTenantAdminApi,
  listTenantAdminsApi,
  removeTenantUserApi,
  revokeTenantAdminApi,
} from "@/controllers/API/tenant";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { Tenant } from "@/types/api/tenant";
import { useTable } from "@/util/hook";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  tenant: Tenant;
  onClose: () => void;
}

// Root tenant rejects admin grants/revokes server-side (errcode 19204).
// Hide the buttons in the UI to avoid surfacing an error path.
const isRootTenant = (tenant: Tenant) => tenant.id === 1;

export function TenantUserDialog({ tenant, onClose }: Props) {
  const { t } = useTranslation("bs");
  const [pickedToAdd, setPickedToAdd] = useState<DepartmentUserOption[]>([]);
  const [addingUsers, setAddingUsers] = useState(false);
  const [adminIds, setAdminIds] = useState<Set<number>>(new Set());
  // ``root_dept_id`` lives on TenantDetail (not TenantListItem) so we fetch it
  // once here to scope the member-picker to the tenant's department subtree.
  const [rootDeptId, setRootDeptId] = useState<number | null>(null);
  const rootTenant = isRootTenant(tenant);

  const {
    page,
    pageSize,
    data: users,
    total,
    setPage,
    search,
    reload,
  } = useTable(
    { pageSize: 10 },
    (param: any) =>
      getTenantUsersApi(tenant.id, {
        page: param.page,
        page_size: param.pageSize,
        keyword: param.keyword,
      })
  );

  const reloadAdmins = () => {
    if (rootTenant) return;
    listTenantAdminsApi(tenant.id)
      .then((res) => setAdminIds(new Set(res?.user_ids || [])))
      .catch(() => setAdminIds(new Set()));
  };

  useEffect(() => {
    reloadAdmins();
    // Resolve the tenant's root_dept_id once; failures degrade gracefully to
    // an unscoped picker (the user-facing impact is just a wider candidate
    // pool — backend still owns final validation).
    getTenantApi(tenant.id)
      .then((detail) => setRootDeptId(detail?.root_dept_id ?? null))
      .catch(() => setRootDeptId(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant.id]);

  const handleAddPicked = () => {
    if (pickedToAdd.length === 0 || addingUsers) return;
    setAddingUsers(true);
    captureAndAlertRequestErrorHoc(
      addTenantUsersApi(tenant.id, {
        user_ids: pickedToAdd.map((u) => Number(u.value)),
      }).then(() => {
        toast({ title: t("updateSuccess"), variant: "success" });
        setPickedToAdd([]);
        reload();
      })
    ).finally(() => setAddingUsers(false));
  };

  const handleRemoveUser = (userId: number) => {
    bsConfirm({
      title: t("tenant.removeUser"),
      desc: t("tenant.confirmRemoveUser"),
      onOk: (next: () => void) => {
        captureAndAlertRequestErrorHoc(
          removeTenantUserApi(tenant.id, userId).then(() => {
            toast({ title: t("updateSuccess"), variant: "success" });
            reload();
            reloadAdmins();
          })
        );
        next();
      },
    });
  };

  const handlePromoteAdmin = (userId: number) => {
    captureAndAlertRequestErrorHoc(
      grantTenantAdminApi(tenant.id, userId).then(() => {
        toast({ title: t("updateSuccess"), variant: "success" });
        reloadAdmins();
      })
    );
  };

  const handleRevokeAdmin = (userId: number) => {
    bsConfirm({
      title: t("tenant.revokeAdmin", { defaultValue: "取消管理员" }),
      desc: t("tenant.confirmRevokeAdmin", {
        defaultValue: "确认取消该用户的管理员身份？",
      }),
      onOk: (next: () => void) => {
        captureAndAlertRequestErrorHoc(
          revokeTenantAdminApi(tenant.id, userId).then(() => {
            toast({ title: t("updateSuccess"), variant: "success" });
            reloadAdmins();
          })
        );
        next();
      },
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 w-[680px] max-h-[80vh] flex flex-col shadow-lg">
        <h3 className="text-lg font-semibold mb-4">
          {t("tenant.users")} - {displayTenantName(tenant.tenant_name)}
        </h3>

        {/* Add User — restricted to the Tenant's department subtree so members
            cannot be silently pulled in from outside (write-side guard for the
            tenant-membership relation). Root Tenant has no mount point, so the
            picker falls back to the full org tree. */}
        <div className="mb-4 flex items-start gap-2">
          <div className="flex-1">
            <DepartmentUsersSelect
              multiple
              value={pickedToAdd}
              onChange={setPickedToAdd}
              rootDeptId={rootDeptId ?? undefined}
              placeholder={t("tenant.addUser")}
              searchPlaceholder={t("tenant.searchUser")}
              emptyMessage={
                rootDeptId != null
                  ? t("tenant.addUserEmptySubtree", {
                      defaultValue:
                        "该子租户子树暂无可加成员，请先在组织树中调整后再添加。",
                    })
                  : undefined
              }
            />
            {rootDeptId != null && (
              <p className="mt-1 text-xs text-muted-foreground">
                {t("tenant.addUserSubtreeHint", {
                  defaultValue:
                    "成员必须来自该子租户的部门子树，不能选取子树外用户。",
                })}
              </p>
            )}
          </div>
          <Button
            type="button"
            onClick={handleAddPicked}
            disabled={pickedToAdd.length === 0 || addingUsers}
          >
            {addingUsers
              ? t("loading", { ns: "bs" })
              : t("tenant.addUserAction", { defaultValue: "添加" })}
          </Button>
        </div>

        {/* Search */}
        <div className="mb-4">
          <SearchInput
            placeholder={t("tenant.searchUser")}
            onChange={(e: any) => search(e.target.value)}
          />
        </div>

        {/* User List */}
        <div className="flex-1 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("system.username")}</TableHead>
                <TableHead>{t("tenant.lastAccess")}</TableHead>
                <TableHead className="text-right">
                  {t("tenant.actions")}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((user: any) => {
                const isAdmin = adminIds.has(user.user_id);
                return (
                  <TableRow key={user.user_id}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {user.avatar ? (
                          <img
                            src={user.avatar}
                            alt=""
                            className="w-6 h-6 rounded-full"
                          />
                        ) : (
                          <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-xs">
                            {user.user_name?.charAt(0)}
                          </div>
                        )}
                        <span>{user.user_name}</span>
                        {isAdmin && (
                          <span className="ml-1 inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                            {t("tenant.adminBadge", { defaultValue: "管理员" })}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.join_time
                        ? user.join_time.replace("T", " ").slice(0, 19)
                        : "-"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-3">
                        {!rootTenant &&
                          (isAdmin ? (
                            <button
                              className="text-sm text-muted-foreground hover:underline"
                              onClick={() => handleRevokeAdmin(user.user_id)}
                            >
                              {t("tenant.revokeAdmin", {
                                defaultValue: "取消管理员",
                              })}
                            </button>
                          ) : (
                            <button
                              className="text-sm text-primary hover:underline"
                              onClick={() => handlePromoteAdmin(user.user_id)}
                            >
                              {t("tenant.promoteAdmin", {
                                defaultValue: "设为管理员",
                              })}
                            </button>
                          ))}
                        <button
                          className="text-red-500 hover:underline text-sm"
                          onClick={() => handleRemoveUser(user.user_id)}
                        >
                          {t("tenant.removeUser")}
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        <div className="flex items-center justify-between mt-4">
          <AutoPagination
            page={page}
            pageSize={pageSize}
            total={total}
            onChange={(newPage: number) => setPage(newPage)}
          />
          <Button variant="outline" onClick={onClose}>
            {t("close")}
          </Button>
        </div>
      </div>
    </div>
  );
}
