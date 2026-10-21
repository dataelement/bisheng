import { userContext } from "@/contexts/userContext";
import { useDshBrowserConfig } from "@/hooks/useDshBrowserConfig";
import { PluginMarketPage } from "@/pages/BuildPage/dsh/PluginMarketPage";
import { DshManagement } from "@/pages/SystemPage/dsh";
import { Tabs } from "@bisheng/ui";
import { useContext, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { DSH_SECTIONS, resolveDshSection, type DshSection } from "./sections";

export default function DshPage() {
  const { user } = useContext(userContext);
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { config } = useDshBrowserConfig();
  const [usageToolbarTarget, setUsageToolbarTarget] = useState<HTMLDivElement | null>(null);
  const canManageDsh = user?.role === "admin" || !!user?.is_global_super || !!user?.is_child_admin;
  const sections = config?.enabled === false ? DSH_SECTIONS.filter(({ value }) => value === "access") : DSH_SECTIONS;
  const section = resolveDshSection(
    location.search,
    sections.map(({ value }) => value satisfies DshSection),
  );

  if (!canManageDsh) return <Navigate to="/403" replace />;
  return (
    <div className="flex h-full w-full flex-col px-2 pt-4">
      <div className="flex min-h-0 w-full flex-1 flex-col">
        {config?.management_enabled && (
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-6 gap-y-3 pr-6" data-dsh-header>
            <Tabs
              activeKey={section}
              onChange={(value) => navigate(`/dsh?tab=${value}`)}
              aria-label={t("dsh.title")}
              items={sections.map(({ value, labelKey }) => ({ key: value, label: t(labelKey) }))}
              className="min-w-0 shrink-0 self-start"
            />
            <div ref={setUsageToolbarTarget} className="ml-auto max-w-full" />
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-hidden">
          {section === "plugins" ? (
            <PluginMarketPage />
          ) : (
            <DshManagement section={section} usageToolbarTarget={usageToolbarTarget} />
          )}
        </div>
      </div>
    </div>
  );
}
