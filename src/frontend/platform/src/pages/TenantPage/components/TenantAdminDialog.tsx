import { resolveUserAvatarUrl } from '@bisheng/identity';
import { Pagination, Button, SearchInput, Tag, UserAvatar, notification } from '@bisheng/ui';
import { useSubjectTable } from "@/components/bs-comp/selectComponent/useSubjectTable";
import { SubjectSearchStatus } from "@/components/bs-comp/selectComponent/SubjectSearchStatus";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import {
  getTenantUsersApi,
  grantTenantAdminApi,
  listTenantAdminsApi,
  revokeTenantAdminApi,
} from "@/controllers/API/tenant";
import { showApiError } from "@/controllers/request";
import type { Tenant, TenantAdminUser, TenantUser } from "@/types/api/tenant";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  tenant: Tenant;
  onClose: () => void;
  /** Called after any grant/revoke so the tenant list column can refresh. */
  onChanged?: () => void;
}

/**
 * Dedicated Child Admin manager. Grants/revokes take effect per click, so the
 * dialog has no confirm/cancel pair — only Close.
 */
export function TenantAdminDialog({ tenant, onClose, onChanged }: Props) {
  const { t } = useTranslation("bs");
  const paginationLocale = usePaginationLocale();
  const [admins, setAdmins] = useState<TenantAdminUser[]>(tenant.admin_users ?? []);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const adminIds = new Set(admins.map((a) => a.user_id));

  const { page, pageSize, data: members, total, setPage, subjectSearch } = useSubjectTable<TenantUser>({ pageSize: 5 }, (param, signal) =>
    getTenantUsersApi(tenant.id, { page: param.page, page_size: param.pageSize, keyword: param.keyword }, { signal }),
  );

  const reloadAdmins = useCallback(() => {
    return listTenantAdminsApi(tenant.id)
      .then((res) => setAdmins(res?.users ?? []))
      .catch(showApiError);
  }, [tenant.id]);

  useEffect(() => {
    reloadAdmins();
  }, [reloadAdmins]);

  const afterChange = () => {
    notification.open({ type: "success", title: String(t("updateSuccess") ?? ''), description: "" });
    onChanged?.();
    return reloadAdmins();
  };

  const handleGrant = (userId: number) => {
    setPendingId(userId);
    grantTenantAdminApi(tenant.id, userId)
      .then(afterChange)
      .catch(showApiError)
      .finally(() => setPendingId(null));
  };

  const handleRevoke = (admin: TenantAdminUser) => {
    bsConfirm({
      title: t("tenant.revokeAdmin"),
      desc: t("tenant.confirmRevokeAdmin"),
      onOk: (next: () => void) =>
        revokeTenantAdminApi(tenant.id, admin.user_id).then(() => {
          next();
          return afterChange();
        }),
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tenant-admin-title"
        className="bg-background rounded-lg p-6 w-[560px] max-w-[calc(100vw-32px)] max-h-[85vh] flex flex-col shadow-lg"
      >
        <h3 id="tenant-admin-title" className="text-lg font-semibold">
          {t("tenant.adminDialogTitle", { name: displayTenantName(tenant.tenant_name) })}
        </h3>
        <p className="text-sm text-muted-foreground mt-1 mb-5">{t("tenant.adminDialogDesc")}</p>

        <div className="flex-1 overflow-y-auto">
          {/* Current admins: the state the operator came here to see. */}
          <section aria-labelledby="tenant-admin-current">
            <h4 id="tenant-admin-current" className="text-sm font-medium mb-2">
              {t("tenant.currentAdmins")}
              <span className="ml-1 text-muted-foreground">({admins.length})</span>
            </h4>
            {admins.length ? (
              <ul className="rounded-md border divide-y">
                {admins.map((admin) => (
                  <li key={admin.user_id} className="flex items-center justify-between px-3 py-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <UserAvatar className="size-6" fallbackClassName="text-xs" name={admin.user_name}
                        src={resolveUserAvatarUrl(admin.avatar, __APP_ENV__.BASE_URL)} />
                      <span className="truncate">{admin.user_name}</span>
                    </div>
                    <Button type="button" size="small" variant="link" color="danger" onClick={() => handleRevoke(admin)}>
                      {t("tenant.revokeAdmin")}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
                {t("tenant.noAdminYet")}
              </p>
            )}
          </section>

          {/* Add: search scoped to this tenant's members. */}
          <section aria-labelledby="tenant-admin-add" className="mt-6">
            <h4 id="tenant-admin-add" className="text-sm font-medium mb-2">
              {t("tenant.addAdmin")}
            </h4>
            <SearchInput placeholder={t("tenant.adminSearchPlaceholder")} {...subjectSearch.inputProps} />
            <SubjectSearchStatus
              tooLong={subjectSearch.tooLong}
              failed={subjectSearch.failed}
              loading={subjectSearch.loading}
              empty={!members.length}
              onRetry={subjectSearch.retry}
            />
            <ul className="mt-2">
              {members.map((user) => {
                const isAdmin = adminIds.has(user.user_id);
                return (
                  <li key={user.user_id} className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-muted/50">
                    <div className="flex items-center gap-2 min-w-0">
                      <UserAvatar className="size-6" fallbackClassName="text-xs" name={user.user_name}
                        src={resolveUserAvatarUrl(user.avatar, __APP_ENV__.BASE_URL)} />
                      <span className="truncate">{user.user_name}</span>
                      {user.external_id && (
                        <span className="text-xs text-muted-foreground truncate">{user.external_id}</span>
                      )}
                    </div>
                    {isAdmin ? (
                      <Tag size="small" className="shrink-0 whitespace-nowrap">{t("tenant.alreadyAdmin")}</Tag>
                    ) : (
                      <Button
                        type="button"
                        size="small"
                        variant="link"
                        loading={pendingId === user.user_id}
                        disabled={pendingId !== null}
                        onClick={() => handleGrant(user.user_id)}
                      >
                        {t("tenant.promoteAdmin")}
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
            {total > pageSize && (
              <div className="flex justify-end mt-2">
                <Pagination locale={paginationLocale} size="small" simple
                  current={page}
                  pageSize={pageSize}
                  total={total}
                  onChange={(newPage: number) => setPage(newPage)}
                />
              </div>
            )}
          </section>
        </div>

        <div className="flex justify-end mt-5">
          <Button variant="outlined" onClick={onClose} color="default">
            {t("close")}
          </Button>
        </div>
      </div>
    </div>
  );
}
