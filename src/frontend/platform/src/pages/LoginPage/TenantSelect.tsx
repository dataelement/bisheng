import { Button } from "@/components/bs-ui/button";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { getUserTenantsApi, switchTenantApi } from "@/controllers/API/tenant";
import { logoutApi } from "@/controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import type { UserTenantItem } from "@/types/api/tenant";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

export default function TenantSelect() {
  const { t } = useTranslation("bs");
  const [tenants, setTenants] = useState<UserTenantItem[]>([]);
  const [loading, setLoading] = useState<number | null>(null);

  useEffect(() => {
    // Try sessionStorage first (from login redirect)
    const cached = sessionStorage.getItem("pending_tenants");
    if (cached) {
      try {
        setTenants(JSON.parse(cached));
        return;
      } catch {
        // fall through
      }
    }
    // Fallback: fetch from API
    captureAndAlertRequestErrorHoc(
      getUserTenantsApi().then((res: any) => {
        setTenants(res || []);
      })
    );
  }, []);

  const handleSelect = (tenantId: number) => {
    setLoading(tenantId);
    captureAndAlertRequestErrorHoc(
      switchTenantApi(tenantId)
        .then(() => {
          sessionStorage.removeItem("pending_tenants");
          toast({ title: t("tenant.switchSuccess"), variant: "success" });
          const path = import.meta.env.DEV ? "/admin" : "/workspace/";
          // @ts-ignore
          location.href = `${__APP_ENV__.BASE_URL}${path}`;
        })
        .catch(() => {
          setLoading(null);
        })
    );
  };

  const handleBackToLogin = () => {
    sessionStorage.removeItem("pending_tenants");
    captureAndAlertRequestErrorHoc(
      logoutApi().then(() => {
        // @ts-ignore
        location.href = __APP_ENV__.BASE_URL || "/";
      })
    );
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-md px-6">
        <h1 className="text-2xl font-bold text-center mb-8">
          {t("tenant.selectTenant")}
        </h1>

        {tenants.length === 0 ? (
          <div className="text-center">
            <p className="text-muted-foreground mb-6">
              {t("tenant.noTenants")}
            </p>
            <Button variant="outline" onClick={handleBackToLogin}>
              {t("tenant.backToLogin")}
            </Button>
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {tenants.map((tenant) => (
                <button
                  key={tenant.tenant_id}
                  className="w-full flex items-center gap-4 p-4 rounded-lg border hover:bg-accent transition-colors text-left disabled:opacity-50"
                  onClick={() => handleSelect(tenant.tenant_id)}
                  disabled={loading !== null}
                >
                  {/* Logo / Avatar */}
                  {tenant.logo ? (
                    <img
                      src={tenant.logo}
                      alt=""
                      className="w-12 h-12 rounded-lg object-cover"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center text-lg font-bold text-primary">
                      {tenant.tenant_name.charAt(0)}
                    </div>
                  )}

                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">
                      {tenant.tenant_name}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {tenant.tenant_code}
                    </p>
                  </div>

                  {loading === tenant.tenant_id && (
                    <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  )}
                </button>
              ))}
            </div>

            <div className="text-center mt-6">
              <button
                className="text-sm text-muted-foreground hover:text-foreground"
                onClick={handleBackToLogin}
              >
                {t("tenant.backToLogin")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
