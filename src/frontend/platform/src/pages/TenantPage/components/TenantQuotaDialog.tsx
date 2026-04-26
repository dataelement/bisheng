import { Button } from "@/components/bs-ui/button";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { getTenantQuotaApi, setTenantQuotaApi } from "@/controllers/API/tenant";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { Tenant, TenantQuota } from "@/types/api/tenant";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  tenant: Tenant;
  onClose: () => void;
  onSuccess: () => void;
}

export function TenantQuotaDialog({ tenant, onClose, onSuccess }: Props) {
  const { t } = useTranslation("bs");
  const [quota, setQuota] = useState<TenantQuota | null>(null);
  const [config, setConfig] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    captureAndAlertRequestErrorHoc(
      getTenantQuotaApi(tenant.id).then((res: any) => {
        setQuota(res);
        setConfig(res.quota_config || {});
      })
    );
  }, [tenant.id]);

  const handleSave = async () => {
    setLoading(true);
    try {
      await captureAndAlertRequestErrorHoc(
        setTenantQuotaApi(tenant.id, config)
      );
      toast({ title: t("updateSuccess"), variant: "success" });
      onSuccess();
    } finally {
      setLoading(false);
    }
  };

  const updateConfig = (key: string, value: string) => {
    const numVal = value === "" ? undefined : Number(value);
    setConfig({ ...config, [key]: numVal });
  };

  const quotaFields = [
    { key: "storage_gb", label: t("tenant.knowledgeStorageUsage") + " (GB)" },
  ];

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 w-[480px] shadow-lg">
        <h3 className="text-lg font-semibold mb-4">
          {t("tenant.quota")} - {displayTenantName(tenant.tenant_name)}
        </h3>

        {quota && (
          <div className="space-y-4">
            {quotaFields.map(({ key, label }) => (
              <div key={key} className="flex items-center justify-between">
                <div className="flex-1">
                  <label className="text-sm font-medium">{label}</label>
                  {quota.usage[key] != null && (
                    <span className="text-xs text-muted-foreground ml-2">
                      ({quota.usage[key]})
                    </span>
                  )}
                </div>
                <input
                  type="number"
                  className="w-24 border rounded px-2 py-1 bg-background text-right"
                  value={config[key] ?? ""}
                  onChange={(e) => updateConfig(key, e.target.value)}
                  min={0}
                  placeholder="-"
                />
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button onClick={handleSave} disabled={loading}>
            {t("confirm")}
          </Button>
        </div>
      </div>
    </div>
  );
}
