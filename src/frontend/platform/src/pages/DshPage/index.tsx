import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { useDshBrowserConfig } from "@/hooks/useDshBrowserConfig";
import { Tabs, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshManagement } from "@/pages/SystemPage/dsh";
import { DshContentSafetySettings } from "@/pages/SystemPage/dsh/DshContentSafetySettings";
import { ModelAuditTenantSelect } from "@/pages/SystemPage/dsh/ModelAuditTenantSelect";
import { displayTenantName } from "@/utils/tenantDisplayName";
import { PluginMarketPage } from "@/pages/BuildPage/dsh/PluginMarketPage";
import { DSH_SECTIONS, resolveDshSection, type DshSection } from "./sections";

export function DshPage() {
  const { user } = useContext(userContext);
  const { appConfig } = useContext(locationContext);
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { config, failed } = useDshBrowserConfig();
  const [usageToolbarTarget, setUsageToolbarTarget] =
    useState<HTMLDivElement | null>(null);
  const canManageDsh =
    user?.role === "admin" || !!user?.is_global_super || !!user?.is_child_admin;
  const canManageSafety = canManageDsh && appConfig.isPro === true;
  const sections = DSH_SECTIONS.filter(({ value }) =>
    config?.enabled === false
      ? value === "access"
      : value !== "content-safety" || canManageSafety,
  );
  const section = resolveDshSection(
    location.search,
    sections.map(({ value }) => value satisfies DshSection),
  );

  const [safetyVisited, setSafetyVisited] = useState(
    section === "content-safety",
  );
  useEffect(() => {
    if (
      !canManageSafety ||
      config?.enabled === false ||
      config?.management_enabled === false
    )
      setSafetyVisited(false);
    else if (section === "content-safety") setSafetyVisited(true);
  }, [section, canManageSafety, config?.enabled, config?.management_enabled]);

  if (!canManageDsh) return <Navigate to="/403" replace />;
  if (
    appConfig.isPro === false &&
    new URLSearchParams(location.search).get("tab") === "content-safety"
  )
    return <Navigate to={`/dsh?tab=${section}`} replace />;
  return (
    <div className="flex h-full w-full flex-col px-2 pt-4">
      <Tabs
        value={section}
        onValueChange={(value) => navigate(`/dsh?tab=${value}`)}
        className="flex min-h-0 w-full flex-1 flex-col"
      >
        {config?.management_enabled && (
          <div
            className="flex shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-3 pr-6"
            data-dsh-header
          >
            <div className="min-w-0 max-w-full overflow-x-auto">
              <TabsList
                aria-label={t("dsh.title")}
                className="shrink-0 self-start"
              >
                {sections.map(({ value, labelKey }) => (
                  <TabsTrigger key={value} value={value}>
                    {t(labelKey)}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
            <div ref={setUsageToolbarTarget} className="ml-auto max-w-full" />
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-hidden">
          {canManageSafety &&
            (section === "content-safety" || safetyVisited) &&
            config?.enabled !== false && (
              <div
                hidden={section !== "content-safety"}
                className="h-full min-h-0 overflow-y-auto px-6 py-5"
              >
                {!config ? (
                  <p role={failed ? "alert" : "status"}>
                    {t(failed ? "dsh.unavailable" : "dsh.loading")}
                  </p>
                ) : !config.management_enabled ? (
                  <p>{t("dsh.managementUnavailable")}</p>
                ) : (
                  <DshContentSafetyTenantPanel
                    key={`${user?.user_id ?? "unknown"}:${user?.leaf_tenant_id ?? user?.tenant_id ?? "unknown"}:${!!user?.is_global_super}:${!!user?.is_child_admin}`}
                  />
                )}
              </div>
            )}
          {section !== "content-safety" &&
            (section === "plugins" ? (
              <PluginMarketPage />
            ) : (
              <DshManagement
                section={section}
                usageToolbarTarget={usageToolbarTarget}
              />
            ))}
        </div>
      </Tabs>
    </div>
  );
}

function DshContentSafetyTenantPanel() {
  const { user } = useContext(userContext);
  const { t } = useTranslation();
  const identity = user as {
    tenant_id?: unknown;
    leaf_tenant_id?: unknown;
    tenant_name?: string;
    leaf_tenant_name?: string;
    is_global_super?: boolean;
    role?: string;
    is_child_admin?: boolean;
  };
  const ownTenant = Number(identity?.leaf_tenant_id ?? identity?.tenant_id);
  const initialTenant =
    Number.isSafeInteger(ownTenant) && ownTenant > 0 ? ownTenant : undefined;
  const [selectedTenant, setTenant] = useState<number | undefined>();
  const global = identity?.is_global_super === true;
  const tenant = global ? selectedTenant : initialTenant;
  const canConfigure =
    identity?.role === "admin" || global || identity?.is_child_admin === true;
  return (
    <div className="min-w-0 space-y-4">
      {global ? (
        <ModelAuditTenantSelect
          initialTenant={initialTenant}
          value={tenant}
          onChange={setTenant}
        />
      ) : (
        <p className="flex flex-wrap gap-2 text-sm">
          <span className="text-muted-foreground">
            {t("dsh.modelAuditView.tenant")}
          </span>
          {displayTenantName(
            identity?.leaf_tenant_name ?? identity?.tenant_name,
          ) || t("dsh.modelAuditView.managed_tenant")}
        </p>
      )}
      <DshContentSafetySettings
        key={tenant ?? "no-tenant"}
        tenantId={tenant}
        canConfigure={canConfigure}
      />
    </div>
  );
}

// Preserve the existing lazy route module's default export.
export default DshPage;
