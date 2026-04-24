import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import AutoPagination from "@/components/bs-ui/pagination/autoPagination";
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
  deleteTenantApi,
  getTenantsApi,
  updateTenantStatusApi,
} from "@/controllers/API/tenant";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useTable } from "@/util/hook";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateTenantDialog } from "./components/CreateTenantDialog";
import { TenantUserDialog } from "./components/TenantUserDialog";
import { TenantQuotaDialog } from "./components/TenantQuotaDialog";
import type { Tenant } from "@/types/api/tenant";

const statusColors: Record<string, string> = {
  active: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
  disabled: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300",
  archived:
    "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300",
};

export default function TenantPage() {
  const { t } = useTranslation("bs");
  const [createOpen, setCreateOpen] = useState(false);
  const [editTenant, setEditTenant] = useState<Tenant | null>(null);
  const [userDialogTenant, setUserDialogTenant] = useState<Tenant | null>(null);
  const [quotaDialogTenant, setQuotaDialogTenant] = useState<Tenant | null>(
    null
  );
  const [deleteConfirmCode, setDeleteConfirmCode] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Tenant | null>(null);

  const {
    page,
    pageSize,
    data: tenants,
    total,
    setPage,
    search,
    reload,
  } = useTable<Tenant>(
    { pageSize: 20 },
    (param: any) =>
      getTenantsApi({
        keyword: param.keyword,
        page: param.page,
        page_size: param.pageSize,
      })
  );

  const handleToggleStatus = (tenant: Tenant) => {
    const newStatus = tenant.status === "active" ? "disabled" : "active";
    if (newStatus === "disabled") {
      bsConfirm({
        title: t("tenant.disable"),
        desc: t("tenant.confirmDisable"),
        onOk: (next: () => void) => {
          captureAndAlertRequestErrorHoc(
            updateTenantStatusApi(tenant.id, newStatus).then(() => {
              toast({ title: t("updateSuccess"), variant: "success" });
              reload();
            })
          );
          next();
        },
      });
    } else {
      captureAndAlertRequestErrorHoc(
        updateTenantStatusApi(tenant.id, newStatus).then(() => {
          toast({ title: t("updateSuccess"), variant: "success" });
          reload();
        })
      );
    }
  };

  const handleDelete = (tenant: Tenant) => {
    setDeleteTarget(tenant);
    setDeleteConfirmCode("");
  };

  const confirmDelete = () => {
    if (!deleteTarget || deleteConfirmCode !== deleteTarget.tenant_code) return;
    captureAndAlertRequestErrorHoc(
      deleteTenantApi(deleteTarget.id).then(() => {
        toast({ title: t("updateSuccess"), variant: "success" });
        setDeleteTarget(null);
        reload();
      })
    );
  };

  return (
    <div className="relative h-full px-2 py-4 overflow-hidden">
      <div className="flex justify-between items-center mb-4">
        <span className="text-lg font-bold">{t("tenant.management")}</span>
        <div className="flex gap-4 items-center">
          <SearchInput
            placeholder={t("tenant.search")}
            onChange={(e: any) => search(e.target.value)}
          />
        </div>
      </div>

      <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200">
        <p className="font-medium">
          {t("tenant.v251Title", { defaultValue: "v2.5.1 租户创建方式已调整" })}
        </p>
        <p className="mt-1 leading-6">
          {t("tenant.v251Desc", {
            defaultValue:
              "Root Tenant 由系统自动初始化；新增子租户需通过部门挂载流程完成。当前页面仅保留现有 Tenant 的查看、编辑、配额和成员管理。",
          })}
        </p>
      </div>

      <div className="h-[calc(100vh-200px)] overflow-y-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("tenant.name")}</TableHead>
              <TableHead>{t("tenant.code")}</TableHead>
              <TableHead>{t("tenant.statusFilter")}</TableHead>
              <TableHead>{t("tenant.userCount")}</TableHead>
              <TableHead>{t("tenant.storageUsage")}</TableHead>
              <TableHead>{t("tenant.createdAt")}</TableHead>
              <TableHead className="text-right">{t("tenant.actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tenants.map((tenant: Tenant) => (
              <TableRow key={tenant.id}>
                <TableCell className="font-medium">
                  <div className="flex items-center gap-2">
                    {tenant.logo ? (
                      <img
                        src={tenant.logo}
                        alt=""
                        className="w-6 h-6 rounded"
                      />
                    ) : (
                      <div className="w-6 h-6 rounded bg-primary/10 flex items-center justify-center text-xs font-bold">
                        {tenant.tenant_name.charAt(0)}
                      </div>
                    )}
                    {tenant.tenant_name}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {tenant.tenant_code}
                </TableCell>
                <TableCell>
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      statusColors[tenant.status] || ""
                    }`}
                  >
                    {t(`tenant.status.${tenant.status}`)}
                  </span>
                </TableCell>
                <TableCell>
                  <button
                    className="text-primary hover:underline cursor-pointer"
                    onClick={() => setUserDialogTenant(tenant)}
                  >
                    {tenant.user_count}
                  </button>
                </TableCell>
                <TableCell>
                  {tenant.storage_quota_gb != null ? (
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-1.5 bg-gray-200 rounded-full dark:bg-gray-700">
                        <div
                          className="h-1.5 bg-primary rounded-full"
                          style={{
                            width: `${Math.min(
                              ((tenant.storage_used_gb || 0) /
                                tenant.storage_quota_gb) *
                                100,
                              100
                            )}%`,
                          }}
                        />
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {tenant.storage_used_gb || 0}/{tenant.storage_quota_gb}
                        GB
                      </span>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {tenant.create_time
                    ? tenant.create_time.replace("T", " ").slice(0, 19)
                    : "-"}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <button
                      className="text-primary hover:underline text-sm"
                      onClick={() => {
                        setEditTenant(tenant);
                        setCreateOpen(true);
                      }}
                    >
                      {t("edit")}
                    </button>
                    <button
                      className="text-primary hover:underline text-sm"
                      onClick={() => setQuotaDialogTenant(tenant)}
                    >
                      {t("tenant.quota")}
                    </button>
                    <button
                      className="text-primary hover:underline text-sm"
                      onClick={() => handleToggleStatus(tenant)}
                    >
                      {tenant.status === "active"
                        ? t("tenant.disable")
                        : t("tenant.enable")}
                    </button>
                    {tenant.status !== "active" && (
                      <button
                        className="text-red-500 hover:underline text-sm"
                        onClick={() => handleDelete(tenant)}
                      >
                        {t("delete")}
                      </button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="bisheng-table-footer bg-background-login">
        <p className="desc">
          {t("tenant.management")}
        </p>
        <AutoPagination
          page={page}
          pageSize={pageSize}
          total={total}
          onChange={(newPage: number) => setPage(newPage)}
        />
      </div>

      {/* Create/Edit Dialog */}
      {createOpen && (
        <CreateTenantDialog
          tenant={editTenant}
          onClose={() => setCreateOpen(false)}
          onSuccess={() => {
            setCreateOpen(false);
            reload();
          }}
        />
      )}

      {/* User Management Dialog */}
      {userDialogTenant && (
        <TenantUserDialog
          tenant={userDialogTenant}
          onClose={() => setUserDialogTenant(null)}
        />
      )}

      {/* Quota Dialog */}
      {quotaDialogTenant && (
        <TenantQuotaDialog
          tenant={quotaDialogTenant}
          onClose={() => setQuotaDialogTenant(null)}
          onSuccess={() => {
            setQuotaDialogTenant(null);
            reload();
          }}
        />
      )}

      {/* Delete Confirmation Dialog */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-background rounded-lg p-6 w-[400px] shadow-lg">
            <h3 className="text-lg font-semibold mb-4">
              {t("tenant.delete")}
            </h3>
            <p className="text-sm text-muted-foreground mb-4">
              {t("tenant.confirmDelete", {
                code: deleteTarget.tenant_code,
              })}
            </p>
            <input
              className="w-full border rounded px-3 py-2 mb-4 bg-background"
              placeholder={t("tenant.enterCodeToConfirm")}
              value={deleteConfirmCode}
              onChange={(e) => setDeleteConfirmCode(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setDeleteTarget(null)}
              >
                {t("cancel")}
              </Button>
              <Button
                variant="destructive"
                disabled={deleteConfirmCode !== deleteTarget.tenant_code}
                onClick={confirmDelete}
              >
                {t("delete")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
