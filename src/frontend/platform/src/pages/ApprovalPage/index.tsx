import { useEffect, useMemo, useState } from "react";
import { toast } from "@/components/bs-ui/toast/use-toast";
import {
  createApprovalRouteApi,
  createApprovalScenarioApi,
  listApprovalExceptionsApi,
  listApprovalRoutesApi,
  listApprovalScenarioPresetsApi,
  listApprovalScenariosApi,
  retryApprovalExceptionApi,
  type ApprovalExceptionItem,
  type ApprovalRouteItem,
  type ApprovalScenarioItem,
  type ApprovalScenarioPreset,
} from "@/controllers/API/approval";
import { useTranslation } from "react-i18next";

function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border-subtle bg-background-primary p-5 shadow-sm">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
        {description ? <p className="mt-1 text-sm text-text-secondary">{description}</p> : null}
      </div>
      {children}
    </section>
  );
}

function EmptyBlock({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border-subtle bg-background-main-content px-4 py-8 text-center text-sm text-text-secondary">
      {text}
    </div>
  );
}

export default function ApprovalPage() {
  const { t } = useTranslation("bs");
  const [loading, setLoading] = useState(false);
  const [presets, setPresets] = useState<ApprovalScenarioPreset[]>([]);
  const [scenarios, setScenarios] = useState<ApprovalScenarioItem[]>([]);
  const [routes, setRoutes] = useState<ApprovalRouteItem[]>([]);
  const [exceptions, setExceptions] = useState<ApprovalExceptionItem[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<number | null>(null);
  const [selectedPresetCode, setSelectedPresetCode] = useState("");
  const [routeName, setRouteName] = useState("");
  const [routeType, setRouteType] = useState("flow");

  const selectedPreset = useMemo(
    () => presets.find((item) => item.scenario_code === selectedPresetCode) ?? null,
    [presets, selectedPresetCode],
  );

  const loadRoutes = async (scenarioId: number) => {
    setRoutes(await listApprovalRoutesApi(scenarioId));
    setSelectedScenarioId(scenarioId);
  };

  const loadPage = async () => {
    setLoading(true);
    try {
      const [presetList, scenarioList, exceptionList] = await Promise.all([
        listApprovalScenarioPresetsApi(),
        listApprovalScenariosApi(),
        listApprovalExceptionsApi(),
      ]);
      setPresets(presetList);
      setScenarios(scenarioList);
      setExceptions(exceptionList);
      const initialScenarioId = selectedScenarioId ?? scenarioList[0]?.id ?? null;
      if (initialScenarioId) {
        await loadRoutes(initialScenarioId);
      } else {
        setRoutes([]);
      }
      if (!selectedPresetCode && presetList[0]?.scenario_code) {
        setSelectedPresetCode(presetList[0].scenario_code);
      }
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.loadFailed")),
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPage();
  }, []);

  const handleCreateScenario = async () => {
    if (!selectedPreset) return;
    try {
      await createApprovalScenarioApi({
        scenario_code: selectedPreset.scenario_code,
        scenario_name: selectedPreset.scenario_name,
        enabled: false,
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.createSuccess"),
      });
      await loadPage();
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.createFailed")),
      });
    }
  };

  const handleRetryException = async (exceptionId: number) => {
    try {
      await retryApprovalExceptionApi(exceptionId);
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.retrySuccess"),
      });
      await loadPage();
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.retryFailed")),
      });
    }
  };

  const handleCreateRoute = async () => {
    if (!selectedScenarioId || !routeName.trim()) return;
    try {
      await createApprovalRouteApi(selectedScenarioId, {
        route_name: routeName.trim(),
        route_type: routeType,
        sort_order: routes.length,
        match_config: {},
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.routeCreateSuccess"),
      });
      setRouteName("");
      await loadRoutes(selectedScenarioId);
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.routeCreateFailed")),
      });
    }
  };

  return (
    <div className="flex h-full w-full flex-col gap-5 bg-background-main-content p-6">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary">{t("approvalPage.title")}</h1>
        <p className="mt-2 text-sm text-text-secondary">{t("approvalPage.subtitle")}</p>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.2fr_1fr]">
        <SectionCard
          title={t("approvalPage.presetTitle")}
          description={t("approvalPage.presetDesc")}
        >
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex min-w-[260px] flex-1 flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.presetSelect")}</span>
              <select
                value={selectedPresetCode}
                onChange={(event) => setSelectedPresetCode(event.target.value)}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              >
                {presets.map((preset) => (
                  <option key={preset.scenario_code} value={preset.scenario_code}>
                    {preset.scenario_name} ({preset.scenario_code})
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!selectedPreset}
              onClick={() => void handleCreateScenario()}
              className="h-10 rounded-lg bg-primary px-4 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t("approvalPage.createScenario")}
            </button>
          </div>
          {selectedPreset && (
            <div className="mt-4 rounded-lg bg-background-main-content p-4 text-sm text-text-secondary">
              <div>{t("approvalPage.handlerKey")}: {selectedPreset.handler_key || "--"}</div>
              <div className="mt-2">
                {t("approvalPage.conditionFields")}: {(selectedPreset.condition_fields || []).join(", ") || "--"}
              </div>
              <div className="mt-2">
                {t("approvalPage.approverSources")}: {(selectedPreset.approver_source_types || []).join(", ") || "--"}
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard
          title={t("approvalPage.exceptionTitle")}
          description={t("approvalPage.exceptionDesc")}
        >
          {!exceptions.length ? (
            <EmptyBlock text={t("approvalPage.emptyExceptions")} />
          ) : (
            <div className="space-y-3">
              {exceptions.map((item) => (
                <div key={item.id} className="rounded-lg border border-border-subtle bg-background-main-content p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-text-primary">
                        {item.exception_type} #{item.id}
                      </div>
                      <div className="mt-1 text-xs text-text-secondary">
                        instance #{item.instance_id || "--"} · {item.status || "--"} · {item.create_time || "--"}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleRetryException(item.id)}
                      className="rounded-lg border border-border-subtle px-3 py-2 text-sm text-text-primary hover:bg-background-primary"
                    >
                      {t("approvalPage.retryAction")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_1fr]">
        <SectionCard
          title={t("approvalPage.scenarioTitle")}
          description={t("approvalPage.scenarioDesc")}
        >
          {loading && !scenarios.length ? (
            <EmptyBlock text={t("approvalPage.loading")} />
          ) : !scenarios.length ? (
            <EmptyBlock text={t("approvalPage.emptyScenarios")} />
          ) : (
            <div className="space-y-3">
              {scenarios.map((scenario) => {
                const active = scenario.id === selectedScenarioId;
                return (
                  <button
                    key={scenario.id}
                    type="button"
                    onClick={() => void loadRoutes(scenario.id)}
                    className={`flex w-full flex-col rounded-lg border px-4 py-3 text-left transition-colors ${
                      active
                        ? "border-primary bg-background-main-content"
                        : "border-border-subtle bg-background-primary hover:bg-background-main-content"
                    }`}
                  >
                    <span className="text-sm font-medium text-text-primary">{scenario.scenario_name}</span>
                    <span className="mt-1 text-xs text-text-secondary">
                      {scenario.scenario_code} · {scenario.enabled ? t("approvalPage.enabled") : t("approvalPage.disabled")}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </SectionCard>

        <SectionCard
          title={t("approvalPage.routeTitle")}
          description={t("approvalPage.routeDesc")}
        >
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <label className="flex min-w-[220px] flex-1 flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.routeNameLabel")}</span>
              <input
                value={routeName}
                onChange={(event) => setRouteName(event.target.value)}
                placeholder={t("approvalPage.routeNamePlaceholder")}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              />
            </label>
            <label className="flex min-w-[160px] flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.routeTypeLabel")}</span>
              <select
                value={routeType}
                onChange={(event) => setRouteType(event.target.value)}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              >
                <option value="flow">{t("approvalPage.routeTypeFlow")}</option>
                <option value="pass">{t("approvalPage.routeTypePass")}</option>
              </select>
            </label>
            <button
              type="button"
              disabled={!selectedScenarioId || !routeName.trim()}
              onClick={() => void handleCreateRoute()}
              className="h-10 rounded-lg bg-primary px-4 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {t("approvalPage.createRoute")}
            </button>
          </div>
          {!routes.length ? (
            <EmptyBlock text={t("approvalPage.emptyRoutes")} />
          ) : (
            <div className="space-y-3">
              {routes.map((route) => (
                <div key={route.id} className="rounded-lg border border-border-subtle bg-background-main-content px-4 py-3">
                  <div className="text-sm font-medium text-text-primary">
                    {route.route_name || route.route_type || t("approvalPage.routeFallback")} #{route.id}
                  </div>
                  <div className="mt-1 text-xs text-text-secondary">
                    {route.route_type || "--"} · {route.enabled ? t("approvalPage.enabled") : t("approvalPage.disabled")}
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
