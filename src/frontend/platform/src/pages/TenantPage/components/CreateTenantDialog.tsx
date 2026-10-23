import { Alert, Button, Input, notification } from '@bisheng/ui';



import { getTenantApi, updateTenantApi } from "@/controllers/API/tenant";
import { showApiError } from "@/controllers/request";
import type { Tenant, TenantUpdateForm } from "@/types/api/tenant";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  tenant: Tenant | null;
  onClose: () => void;
  onSuccess: () => void;
}

// Keep the legacy export; live callers only open this dialog for editing.
export function CreateTenantDialog({ tenant, onClose, onSuccess }: Props) {
  const { t } = useTranslation("bs");
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState<TenantUpdateForm>({ tenant_name: "" });
  const [code, setCode] = useState("");

  useEffect(() => {
    if (!tenant) return;
    getTenantApi(tenant.id).then((res) => {
        setCode(res.tenant_code);
        setForm({
          tenant_name: res.tenant_name,
          contact_name: res.contact_name || "",
          contact_phone: res.contact_phone || "",
          contact_email: res.contact_email || "",
          logo: res.logo || "",
        });
      }).catch(showApiError);
  }, [tenant]);

  const handleSubmit = async () => {
        if ((String(form.tenant_name ?? "").length > 128) || (String((code) ?? '').length > 64)) return;

    if (!tenant || !form.tenant_name?.trim()) return;
    setLoading(true);
    try {
      await updateTenantApi(tenant.id, form);
      notification.open({ type: "success", title: String(t("updateSuccess") ?? ''), description: "" });
      onSuccess();
    } catch (error) {
      showApiError(error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="tenant-edit-title"
        className="bg-background rounded-lg p-6 w-[520px] max-h-[90vh] overflow-y-auto shadow-lg"
      >
        <h3 id="tenant-edit-title" className="text-lg font-semibold mb-4">
          {tenant ? t("tenant.edit") : t("tenant.create")}
        </h3>
        {!tenant && (
          <Alert
            type="warning"
            className="mb-4"
            description={t("tenant.createDeprecatedDesc")}
          />
        )}
        <div className="space-y-4">
          <div>
            <label htmlFor="tenant-edit-name" className="text-sm font-medium block mb-1">
              {t("tenant.name")}{" "}
              <span aria-hidden className="text-red-500">
                *
              </span>
            </label>
            <Input id="tenant-edit-name" value={form.tenant_name ?? ""} onChange={(e) => setForm({ ...form, tenant_name: e.target.value })} maxLength={128} className={"w-full"} showCount />
          </div>
          <div>
            <label htmlFor="tenant-edit-code" className="text-sm font-medium block mb-1">
              {t("tenant.code")}{" "}
              <span aria-hidden className="text-red-500">
                *
              </span>
            </label>
            <Input id="tenant-edit-code" value={code} disabled maxLength={64} className={"w-full"} showCount />
            <p className="text-xs text-muted-foreground mt-1">{t("tenant.codeImmutable")}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6">
          <Button variant="outlined" onClick={onClose} color="default">
            {t("cancel")}
          </Button>
          <Button loading={loading} onClick={handleSubmit} disabled={((String(form.tenant_name ?? "").length > 128) || (String((code) ?? '').length > 64)) || (Boolean(loading) || (!tenant || !form.tenant_name?.trim()))}>
            {t("confirm")}
          </Button>
        </div>
      </div>
    </div>
  );
}
