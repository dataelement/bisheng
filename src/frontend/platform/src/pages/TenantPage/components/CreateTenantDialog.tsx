// @ts-strict-ignore
import { useSubjectSearch } from "@/components/bs-comp/selectComponent/useSubjectSearch"
import { SubjectBusinessId, SubjectSearchStatus } from "@/components/bs-comp/selectComponent/SubjectSearchStatus"
import type { User } from "@/types/api/user"
import { Button } from "@/components/bs-ui/button";
import { toast } from "@/components/bs-ui/toast/use-toast";
import {
  createTenantApi,
  getTenantApi,
  updateTenantApi,
} from "@/controllers/API/tenant";
import { getUsersApi } from "@/controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { Tenant, TenantCreateForm, TenantDetail } from "@/types/api/tenant";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  tenant: Tenant | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function CreateTenantDialog({ tenant, onClose, onSuccess }: Props) {
  const { t } = useTranslation("bs");
  const isEdit = !!tenant;
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<TenantDetail | null>(null);

  const [form, setForm] = useState<TenantCreateForm>({
    tenant_name: "",
    tenant_code: "",
    admin_user_ids: [],
  });

  const userQuery = useSubjectSearch<User>({ emptyByDefault: true,
    fetchPage: (keyword, page, signal) => getUsersApi({ page, pageSize: 10, name: keyword }, { signal }),
  });
  const userSearch = userQuery.keyword;
  const userOptions = userQuery.rows;
  const setUserSearch = userQuery.changeKeyword;
  const [selectedAdmins, setSelectedAdmins] = useState<any[]>([]);

  useEffect(() => {
    if (isEdit && tenant) {
      captureAndAlertRequestErrorHoc(
        getTenantApi(tenant.id).then((res: any) => {
          setDetail(res);
          setForm({
            tenant_name: res.tenant_name,
            tenant_code: res.tenant_code,
            contact_name: res.contact_name || "",
            contact_phone: res.contact_phone || "",
            contact_email: res.contact_email || "",
            logo: res.logo || "",
            admin_user_ids: res.admin_users?.map((u: any) => u.user_id) || [],
          });
          setSelectedAdmins(
            res.admin_users?.map((u: any) => ({
              user_id: u.user_id,
              user_name: u.user_name,
              external_id: u.external_id,
            })) || []
          );
        })
      );
    }
  }, [isEdit, tenant]);

  const addAdmin = (user: any) => {
    if (selectedAdmins.find((a) => a.user_id === user.user_id)) return;
    setSelectedAdmins([...selectedAdmins, user]);
    setForm({
      ...form,
      admin_user_ids: [...form.admin_user_ids, user.user_id],
    });
    setUserSearch("");
  };

  const removeAdmin = (userId: number) => {
    setSelectedAdmins(selectedAdmins.filter((a) => a.user_id !== userId));
    setForm({
      ...form,
      admin_user_ids: form.admin_user_ids.filter((id) => id !== userId),
    });
  };

  const handleSubmit = async () => {
    if (!isEdit) {
      toast({
        title: t("tenant.createDeprecatedTitle", { defaultValue: "新建入口已停用" }),
        description: t("tenant.createDeprecatedDesc", {
          defaultValue: "请通过部门挂载流程创建子租户；Root Tenant 由系统自动初始化。",
        }),
        variant: "warning",
      });
      return;
    }
    if (!form.tenant_name.trim()) return;
    if (!isEdit && !form.tenant_code.trim()) return;
    if (!isEdit && form.admin_user_ids.length === 0) return;

    setLoading(true);
    try {
      if (isEdit && tenant) {
        await captureAndAlertRequestErrorHoc(
          updateTenantApi(tenant.id, {
            tenant_name: form.tenant_name,
            logo: form.logo,
            contact_name: form.contact_name,
            contact_phone: form.contact_phone,
            contact_email: form.contact_email,
          })
        );
      } else {
        await captureAndAlertRequestErrorHoc(createTenantApi(form));
      }
      toast({
        title: isEdit ? t("updateSuccess") : t("createSuccess"),
        variant: "success",
      });
      onSuccess();
    } finally {
      setLoading(false);
    }
  };

  const codeValid = /^[a-zA-Z][a-zA-Z0-9_-]{1,63}$/.test(form.tenant_code);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 w-[520px] max-h-[90vh] overflow-y-auto shadow-lg">
        <h3 className="text-lg font-semibold mb-4">
          {isEdit ? t("tenant.edit") : t("tenant.create")}
        </h3>

        {!isEdit && (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950 dark:text-amber-100">
            {t("tenant.createDeprecatedDesc", {
              defaultValue: "请通过部门挂载流程创建子租户；Root Tenant 由系统自动初始化。",
            })}
          </div>
        )}

        <div className="space-y-4">
          {/* Tenant Name */}
          <div>
            <label className="text-sm font-medium block mb-1">
              {t("tenant.name")} <span className="text-red-500">*</span>
            </label>
            <input
              className="w-full border rounded px-3 py-2 bg-background"
              value={form.tenant_name}
              onChange={(e) =>
                setForm({ ...form, tenant_name: e.target.value })
              }
              maxLength={128}
            />
          </div>

          {/* Tenant Code */}
          <div>
            <label className="text-sm font-medium block mb-1">
              {t("tenant.code")} <span className="text-red-500">*</span>
            </label>
            <input
              className="w-full border rounded px-3 py-2 bg-background disabled:opacity-50"
              value={form.tenant_code}
              onChange={(e) =>
                setForm({ ...form, tenant_code: e.target.value })
              }
              disabled={isEdit}
              maxLength={64}
            />
            <p className="text-xs text-muted-foreground mt-1">
              {isEdit ? t("tenant.codeImmutable") : t("tenant.codeRule")}
            </p>
            {!isEdit && form.tenant_code && !codeValid && (
              <p className="text-xs text-red-500 mt-1">
                {t("tenant.codeRule")}
              </p>
            )}
          </div>

          {/* Admin Selection (create only) */}
          {!isEdit && (
            <div>
              <label className="text-sm font-medium block mb-1">
                {t("tenant.adminSelect")}{" "}
                <span className="text-red-500">*</span>
              </label>
              <input
                className="w-full border rounded px-3 py-2 bg-background"
                placeholder={t("subjectSearch.userPlaceholder")}
                {...userQuery.inputProps}
              />
              <SubjectSearchStatus tooLong={userQuery.tooLong} failed={userQuery.failed} loading={userQuery.loading} empty={!!userSearch && !userOptions.length} onRetry={userQuery.retry} />
              {!userQuery.loading && userOptions.length > 0 && (
                <div
                  className="border rounded mt-1 max-h-32 overflow-y-auto bg-background"
                  onScroll={(event) => {
                    const element = event.currentTarget;
                    if (element.scrollTop + element.clientHeight >= element.scrollHeight - 40) userQuery.loadMore();
                  }}
                >
                  {userOptions.map((user: any) => (
                    <div
                      key={user.user_id}
                      className="px-3 py-2 hover:bg-accent cursor-pointer text-sm"
                      onClick={() => addAdmin(user)}
                    >
                      {user.user_name} <SubjectBusinessId value={user.external_id} />
                    </div>
                  ))}
                  {!userQuery.failed && !userQuery.tooLong && userOptions.length < userQuery.total && (
                    <button type="button" onClick={userQuery.loadMore}>{t("subjectSearch.loadMore")}</button>
                  )}
                </div>
              )}
              {selectedAdmins.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {selectedAdmins.map((admin) => (
                    <span
                      key={admin.user_id}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-accent rounded text-sm"
                    >
                      {admin.user_name} <SubjectBusinessId value={admin.external_id} />
                      <button
                        className="text-muted-foreground hover:text-foreground"
                        onClick={() => removeAdmin(admin.user_id)}
                      >
                        x
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={
              loading ||
              !isEdit ||
              !form.tenant_name.trim() ||
              (!isEdit && (!codeValid || form.admin_user_ids.length === 0))
            }
          >
            {t("confirm")}
          </Button>
        </div>
      </div>
    </div>
  );
}
