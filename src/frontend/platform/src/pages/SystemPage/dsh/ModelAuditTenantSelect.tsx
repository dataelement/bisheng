import { Button } from "@/components/bs-ui/button";
import { getTenantsApi } from "@/controllers/API/tenant";
import type { Tenant } from "@/types/api/tenant";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshChoice } from "./common";

interface ModelAuditTenantSelectProps {
  initialTenant?: number;
  value?: number;
  onChange: (tenantId: number) => void;
}

export function ModelAuditTenantSelect({
  initialTenant,
  value,
  onChange,
}: ModelAuditTenantSelectProps) {
  const { t } = useTranslation();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    const load = async () => {
      const rows = new Map<number, Tenant>();
      for (let page = 1; ; page++) {
        const result = await getTenantsApi({ page, page_size: 100 });
        if (cancelled) return;
        for (const tenant of result.data) {
          if (Number.isSafeInteger(tenant.id) && tenant.id > 0)
            rows.set(tenant.id, tenant);
        }
        if (result.data.length === 0 || page * 100 >= result.total) break;
      }
      setTenants([...rows.values()]);
      if (initialTenant !== undefined && rows.has(initialTenant))
        onChange(initialTenant);
    };
    void load()
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialTenant, onChange, revision]);

  return (
    <div className="space-y-2">
      <span className="block text-sm">{t("dsh.modelAuditView.tenant")}</span>
      <DshChoice
        label={t("dsh.modelAuditView.selectTenant")}
        value={value === undefined ? "" : String(value)}
        disabled={loading || failed || tenants.length === 0}
        options={tenants.map((tenant) => ({
          value: String(tenant.id),
          label: `${displayTenantName(tenant.tenant_name) || tenant.tenant_code} (${tenant.tenant_code})`,
        }))}
        onChange={(selected) => {
          const tenant = tenants.find((item) => String(item.id) === selected);
          if (tenant) onChange(tenant.id);
        }}
      />
      {loading && <p role="status">{t("dsh.loading")}</p>}
      {failed && (
        <div role="alert" className="flex flex-wrap items-center gap-2">
          <span>{t("dsh.modelAuditView.tenantLoadError")}</span>
          <Button
            variant="outline"
            onClick={() => setRevision((old) => old + 1)}
          >
            {t("dsh.refresh")}
          </Button>
        </div>
      )}
      {!loading && !failed && tenants.length === 0 && (
        <p role="status">{t("dsh.modelAuditView.noTenants")}</p>
      )}
    </div>
  );
}
