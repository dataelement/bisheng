import { Button } from "@/components/bs-ui/button";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { getTenantQuotaApi, setTenantQuotaApi } from "@/controllers/API/tenant";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { Tenant, TenantQuota } from "@/types/api/tenant";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

interface Props {
  tenant: Tenant;
  onClose: () => void;
  onSuccess: () => void;
}

// GB float quota: -1 (unlimited), or 0.1 ~ 999 with at most 1 decimal place.
// Mirrors the backend QuotaService._validate_gb_float_quota rules so the
// dialog rejects bad input client-side before triggering a 24005 round-trip.
function validateGbFloat(raw: string, t: (k: string) => string): string {
  if (raw === "") return "";
  const num = Number(raw);
  if (!Number.isFinite(num)) return t("tenant.quotaInvalidNumber");
  if (num < 0.1) return t("tenant.quotaTooSmall");
  if (num > 999) return t("tenant.quotaTooLarge");
  // Reject more than one decimal place; tolerate floating-point noise (e.g. 1.1*10).
  if (Math.abs(Math.round(num * 10) - num * 10) > 1e-6) {
    return t("tenant.quotaPrecision");
  }
  return "";
}

export function TenantQuotaDialog({ tenant, onClose, onSuccess }: Props) {
  const { t } = useTranslation("bs");
  const [quota, setQuota] = useState<TenantQuota | null>(null);
  // Inputs are kept as raw strings so partial edits ("0.", "") render predictably;
  // serialization to numbers happens once at submit time.
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    captureAndAlertRequestErrorHoc(
      getTenantQuotaApi(tenant.id).then((res: any) => {
        setQuota(res);
        const cfg = (res?.quota_config ?? {}) as Record<string, any>;
        const next: Record<string, string> = {};
        Object.keys(cfg).forEach((k) => {
          // -1 means "unlimited"; render as empty so the user can either keep
          // it unlimited (leave blank) or enter a positive cap.
          next[k] = cfg[k] === -1 || cfg[k] == null ? "" : String(cfg[k]);
        });
        setInputs(next);
      })
    );
  }, [tenant.id]);

  const quotaFields = useMemo(
    () => [
      { key: "storage_gb", label: t("tenant.knowledgeStorageUsage") + " (GB)" },
    ],
    [t]
  );

  const errors = useMemo(() => {
    const map: Record<string, string> = {};
    quotaFields.forEach(({ key }) => {
      map[key] = validateGbFloat(inputs[key] ?? "", t);
    });
    return map;
  }, [inputs, quotaFields, t]);

  const hasError = Object.values(errors).some((e) => e !== "");

  const handleChange = (key: string, value: string) => {
    setInputs((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    if (hasError) return;
    const config: Record<string, number> = {};
    quotaFields.forEach(({ key }) => {
      const raw = inputs[key];
      if (raw && raw !== "") {
        // Round to 1 decimal so trailing zeros / precision noise never surface
        // a fresh validation error after a successful save → reload cycle.
        config[key] = Math.round(Number(raw) * 10) / 10;
      }
    });
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

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-lg p-6 w-[480px] shadow-lg">
        <h3 className="text-lg font-semibold mb-4">
          {t("tenant.quota")} - {displayTenantName(tenant.tenant_name)}
        </h3>

        {quota && (
          <div className="space-y-4">
            {quotaFields.map(({ key, label }) => {
              const error = errors[key];
              return (
                <div key={key} className="flex items-start justify-between gap-4">
                  <div className="flex-1 pt-1">
                    <label className="text-sm font-medium">{label}</label>
                    {quota.usage[key] != null && (
                      <span className="text-xs text-muted-foreground ml-2">
                        ({quota.usage[key]})
                      </span>
                    )}
                  </div>
                  <div className="flex flex-col items-end">
                    <input
                      type="number"
                      className={`w-28 border rounded px-2 py-1 bg-background text-right ${
                        error ? "border-red-500 focus:outline-red-500" : ""
                      }`}
                      value={inputs[key] ?? ""}
                      onChange={(e) => handleChange(key, e.target.value)}
                      min={0.1}
                      max={999}
                      step={0.1}
                      placeholder={t("tenant.quotaPlaceholder")}
                    />
                    {error && (
                      <p className="text-xs text-red-500 mt-1 max-w-[180px] text-right">
                        {error}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button onClick={handleSave} disabled={loading || hasError}>
            {t("confirm")}
          </Button>
        </div>
      </div>
    </div>
  );
}
