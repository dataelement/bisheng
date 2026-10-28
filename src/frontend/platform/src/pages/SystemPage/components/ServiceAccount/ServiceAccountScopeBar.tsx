import { Select } from "@bisheng/ui";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { handleUiRequest, showApiError } from "@/controllers/request";
import type { Tenant } from "@/types/api/tenant";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { loadActiveServiceAccountTenants } from "./useServiceAccountManagementScope";

interface ServiceAccountScopeBarProps {
  tenantId: number | null;
  disabled: boolean;
  onChange: (tenantId: number) => Promise<void>;
}

export function ServiceAccountScopeBar({
  tenantId,
  disabled,
  onChange,
}: ServiceAccountScopeBarProps) {
  const { t } = useTranslation();
  const labels = useSelectLabels();
  const labelId = useId();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    void loadActiveServiceAccountTenants()
      .then((rows) => {
        if (active) setTenants(rows);
      })
      .catch(showApiError)
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  const options = tenants.map((row) => ({
    value: row.id,
    label: displayTenantName(row.tenant_name) || row.tenant_code,
  }));
  if (tenantId != null && !options.some((row) => row.value === tenantId)) {
    options.push({ value: tenantId, label: String(tenantId) });
  }
  return (
    <div className="mb-4 space-y-2">
      <div className="flex items-center gap-2">
        <span id={labelId} className="shrink-0 text-sm text-text-2">
          {t("openApiManagement.tenantScope.label")}
        </span>
        <Select
          {...labels}
          aria-labelledby={labelId}
          className="w-48"
          options={options}
          value={tenantId ?? undefined}
          loading={loading}
          disabled={disabled}
          placeholder={t("openApiManagement.tenantScope.choose")}
          onChange={handleUiRequest(async (value) => {
            const id = Number(value);
            if (Number.isInteger(id) && id > 0) await onChange(id);
          })}
        />
      </div>
      <p className="text-sm text-muted-foreground">
        {t("openApiManagement.tenantScope.hint")}
      </p>
    </div>
  );
}
