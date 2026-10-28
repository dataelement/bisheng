import { Pagination, Button, Input, SearchInput, notification } from '@bisheng/ui';
import { Tag, type TagColor } from "@bisheng/ui";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";


import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";

import { deleteTenantApi, getTenantsApi, updateTenantStatusApi } from "@/controllers/API/tenant";
import { showApiError } from "@/controllers/request";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { useTable } from "@/util/hook";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { CreateTenantDialog } from "./components/CreateTenantDialog";
import { TenantUserDialog } from "./components/TenantUserDialog";
import { TenantQuotaDialog } from "./components/TenantQuotaDialog";
import { isGlobalSuperUser } from "@/pages/ModelPage/manage/permissions";
import type { Tenant } from "@/types/api/tenant";

const statusColors: Record<string, TagColor> = { active: "success", disabled: "default", archived: "warning" };

// Root tenant is system-protected (INV-T11): disable/archive/delete are
// rejected server-side with errcode 22008. Hide the disable button to avoid
// surfacing an error path; edit/quota remain allowed.
const isRootTenant = (tenant: Tenant) => tenant.id === 1;

// The /tenant route currently uses permission='sys' so the route guard
// admits Child Admins (routes/index.tsx falls 'sys' back for them). But
// every API this page calls is super-only (get_admin_user) — a Child
// Admin landing here would trip the request.ts 403 → /403 redirect.
// Wrap so the inner component (with all its hooks) only mounts for
// global super admins; everyone else gets bounced to /sys.
export default function TenantPage() {
  const { user } = useContext(userContext);
  if (!isGlobalSuperUser(user)) {
    return <Navigate to="/sys" replace />;
  }
  return <TenantPageInner />;
}

function TenantPageInner() {
  const { t } = useTranslation("bs");
  const paginationLocale = usePaginationLocale();
  const { appConfig } = useContext(locationContext);
  const multiTenantEnabled = !!appConfig?.multiTenantEnabled;
  const [createOpen, setCreateOpen] = useState(false);
  const [editTenant, setEditTenant] = useState<Tenant | null>(null);
  const [userDialogTenant, setUserDialogTenant] = useState<Tenant | null>(null);
  const [quotaDialogTenant, setQuotaDialogTenant] = useState<Tenant | null>(null);
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
    { pageSize: 20, unInitData: !multiTenantEnabled },
    (param: { keyword: string; page: number; pageSize: number }) =>
      getTenantsApi({
        keyword: param.keyword,
        page: param.page,
        page_size: param.pageSize,
      }),
  );

  const handleToggleStatus = (tenant: Tenant) => {
    const newStatus = tenant.status === "active" ? "disabled" : "active";
    if (newStatus === "disabled") {
      bsConfirm({
        title: t("tenant.disable"),
        desc: t("tenant.confirmDisable"),
        onOk: (next: () => void) => {
          return updateTenantStatusApi(tenant.id, newStatus).then(() => {
              notification.open({ type: "success", title: String(t("updateSuccess") ?? ''), description: "" });
              reload();
              next();
            });
        },
      });
    } else {
      updateTenantStatusApi(tenant.id, newStatus).then(() => {
          notification.open({ type: "success", title: String(t("updateSuccess") ?? ''), description: "" });
          reload();
        }).catch(showApiError);
    }
  };

  const handleDelete = (tenant: Tenant) => {
    setDeleteTarget(tenant);
    setDeleteConfirmCode("");
  };

  const confirmDelete = () => {
    if (!deleteTarget || deleteConfirmCode !== deleteTarget.tenant_code) return;
    deleteTenantApi(deleteTarget.id).then(() => {
        notification.open({ type: "success", title: String(t("updateSuccess") ?? ''), description: "" });
        setDeleteTarget(null);
        reload();
      }).catch(showApiError);
  };

  // Tenant CRUD only makes sense in multi-tenant deployments. The route is
  // permission-gated ('sys') but a super admin could still hit /tenant by URL
  // in a single-tenant install; redirect home to keep the Root tenant safe.
  if (!multiTenantEnabled) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="relative h-full px-2 py-4 overflow-hidden">
      <div className="flex justify-between items-center mb-4">
        <span className="text-lg font-bold">{t("tenant.management")}</span>
        <div className="flex gap-4 items-center">
          <SearchInput placeholder={t("tenant.search")} onChange={(e) => search(e.target.value)} />
        </div>
      </div>

      <div className="h-[calc(100vh-200px-var(--license-banner-h,0px))] overflow-y-auto">
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
            {tenants.map((tenant: Tenant) => {
              const tenantLabel = displayTenantName(tenant.tenant_name);
              return (
                <TableRow key={tenant.id}>
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      {tenant.logo ? (
                        <img src={tenant.logo} alt="" className="w-6 h-6 rounded" />
                      ) : (
                        <div className="w-6 h-6 rounded bg-primary/10 flex items-center justify-center text-xs font-bold">
                          {tenantLabel.charAt(0)}
                        </div>
                      )}
                      {tenantLabel}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{tenant.tenant_code}</TableCell>
                  <TableCell>
                    <Tag
                      size="small"
                      dot
                      color={statusColors[tenant.status] ?? "default"}
                      className="shrink-0 whitespace-nowrap"
                    >
                      {t(`tenant.status.${tenant.status}`)}
                    </Tag>
                  </TableCell>
                  <TableCell>
                    <Button type="button" size="small" variant="link" onClick={() => setUserDialogTenant(tenant)}>
                      {tenant.user_count}
                    </Button>
                  </TableCell>
                  <TableCell>
                    {tenant.storage_quota_gb != null ? (
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-gray-200 rounded-full dark:bg-gray-700">
                          <div
                            className="h-1.5 bg-primary rounded-full"
                            style={{
                              width: `${Math.min(
                                ((tenant.storage_used_gb || 0) / tenant.storage_quota_gb) * 100,
                                100,
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
                    {tenant.create_time ? tenant.create_time.replace("T", " ").slice(0, 19) : "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      {/* archived = terminal post-unmount state. The row is
                        read-only: no edit / quota / toggle, only physical
                        delete. Treating archived as "non-active and therefore
                        enable-able" was the bug that resurrected unmounted
                        tenants with no mount point. */}
                      {tenant.status !== "archived" && (
                        <>
                          <Button type="button" size="small" variant="link" onClick={() => {
                              setEditTenant(tenant);
                              setCreateOpen(true);
                            }}>
                            {t("edit")}
                          </Button>
                          <Button type="button" size="small" variant="link" onClick={() => setQuotaDialogTenant(tenant)}>
                            {t("tenant.quota")}
                          </Button>
                          {!isRootTenant(tenant) && (
                            <Button type="button" size="small" variant="link" onClick={() => handleToggleStatus(tenant)}>
                              {tenant.status === "active" ? t("tenant.disable") : t("tenant.enable")}
                            </Button>
                          )}
                        </>
                      )}
                      {tenant.status !== "active" && (
                        <Button type="button" size="small" variant="link" color="danger" onClick={() => handleDelete(tenant)}>
                          {t("delete")}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="bisheng-table-footer bg-background-login">
        <p className="desc">{t("tenant.management")}</p>
        <Pagination locale={paginationLocale}
          current={page}
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
      {userDialogTenant && <TenantUserDialog tenant={userDialogTenant} onClose={() => setUserDialogTenant(null)} />}

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
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="tenant-delete-title"
            className="bg-background rounded-lg p-6 w-[400px] shadow-lg"
          >
            <h3 id="tenant-delete-title" className="text-lg font-semibold mb-4">
              {t("tenant.delete")}
            </h3>
            <p className="text-sm text-muted-foreground mb-4">
              {t("tenant.confirmDelete", {
                code: deleteTarget.tenant_code,
              })}
            </p>
            <Input aria-label={t("tenant.enterCodeToConfirm")} placeholder={t("tenant.enterCodeToConfirm")} value={deleteConfirmCode} onChange={(e) => setDeleteConfirmCode(e.target.value)} className={"w-full mb-4"} />
            <div className="flex justify-end gap-2">
              <Button variant="outlined" onClick={() => setDeleteTarget(null)} color="default">
                {t("cancel")}
              </Button>
              <Button variant="solid" disabled={deleteConfirmCode !== deleteTarget.tenant_code} onClick={confirmDelete} color="danger">
                {t("delete")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
