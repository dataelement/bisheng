import { useEffect, useMemo, useState } from "react";
import { toast } from "@/components/bs-ui/toast/use-toast";
import {
  createApprovalFlowApi,
  createApprovalNodeApi,
  createApprovalRouteApi,
  createApprovalScenarioApi,
  updateApprovalFlowApi,
  updateApprovalNodeApi,
  updateApprovalRouteApi,
  listApprovalFlowsApi,
  listApprovalExceptionsApi,
  listApprovalNodesApi,
  listApprovalRoutesApi,
  listApprovalScenarioPresetsApi,
  listApprovalScenariosApi,
  retryApprovalExceptionApi,
  updateApprovalScenarioApi,
  type ApprovalExceptionItem,
  type ApprovalFlowItem,
  type ApprovalNodeItem,
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
  const [flows, setFlows] = useState<ApprovalFlowItem[]>([]);
  const [nodes, setNodes] = useState<ApprovalNodeItem[]>([]);
  const [exceptions, setExceptions] = useState<ApprovalExceptionItem[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<number | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState<number | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<number | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(null);
  const [selectedPresetCode, setSelectedPresetCode] = useState("");
  const [routeName, setRouteName] = useState("");
  const [routeType, setRouteType] = useState("flow");
  const [routeFlowDefinitionId, setRouteFlowDefinitionId] = useState<string>("");
  const [flowName, setFlowName] = useState("");
  const [flowCode, setFlowCode] = useState("");
  const [nodeName, setNodeName] = useState("");
  const [nodeCode, setNodeCode] = useState("");
  const [nodeMode, setNodeMode] = useState("or");
  const [nodeApproverConfigText, setNodeApproverConfigText] = useState("{}");
  const [exceptionApproverInputs, setExceptionApproverInputs] = useState<Record<number, string>>({});

  const selectedPreset = useMemo(
    () => presets.find((item) => item.scenario_code === selectedPresetCode) ?? null,
    [presets, selectedPresetCode],
  );

  const loadRoutes = async (scenarioId: number) => {
    setRoutes(await listApprovalRoutesApi(scenarioId));
    setSelectedScenarioId(scenarioId);
  };

  const loadFlows = async (scenarioId: number) => {
    const flowList = await listApprovalFlowsApi(scenarioId);
    setFlows(flowList);
    const nextFlowId = selectedFlowId && flowList.some((item) => item.id === selectedFlowId) ? selectedFlowId : flowList[0]?.id ?? null;
    setSelectedFlowId(nextFlowId);
    if (nextFlowId) {
      setNodes(await listApprovalNodesApi(nextFlowId));
    } else {
      setNodes([]);
    }
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
        await Promise.all([loadRoutes(initialScenarioId), loadFlows(initialScenarioId)]);
      } else {
        setRoutes([]);
        setFlows([]);
        setNodes([]);
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

  const handleToggleScenario = async (scenario: ApprovalScenarioItem) => {
    try {
      await updateApprovalScenarioApi(scenario.id, {
        enabled: !scenario.enabled,
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.scenarioUpdateSuccess"),
      });
      await loadPage();
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.scenarioUpdateFailed")),
      });
    }
  };

  const handleRetryException = async (
    item: ApprovalExceptionItem,
    payload: {
      action?: string;
      approver_user_ids?: number[];
    } = {},
  ) => {
    try {
      await retryApprovalExceptionApi(item.id, payload);
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.exceptionResolveSuccess"),
      });
      setExceptionApproverInputs((current) => ({
        ...current,
        [item.id]: "",
      }));
      await loadPage();
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.exceptionResolveFailed")),
      });
    }
  };

  const handleAssignApprovers = async (item: ApprovalExceptionItem) => {
    const rawValue = exceptionApproverInputs[item.id] || "";
    const approverUserIds = rawValue
      .split(",")
      .map((part) => Number(part.trim()))
      .filter((value) => Number.isInteger(value) && value > 0);
    if (!approverUserIds.length) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: t("approvalPage.approverIdsRequired"),
      });
      return;
    }
    await handleRetryException(item, {
      action: "assign_approvers",
      approver_user_ids: approverUserIds,
    });
  };

  const handleCreateRoute = async () => {
    if (!selectedScenarioId || !routeName.trim()) return;
    try {
      await createApprovalRouteApi(selectedScenarioId, {
        route_name: routeName.trim(),
        route_type: routeType,
        sort_order: routes.length,
        flow_definition_id: routeType === "flow" && routeFlowDefinitionId ? Number(routeFlowDefinitionId) : null,
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

  const resetRouteForm = () => {
    setSelectedRouteId(null);
    setRouteName("");
    setRouteType("flow");
    setRouteFlowDefinitionId("");
  };

  const handleCreateFlow = async () => {
    if (!selectedScenarioId || !flowName.trim() || !flowCode.trim()) return;
    try {
      await createApprovalFlowApi(selectedScenarioId, {
        flow_code: flowCode.trim(),
        flow_name: flowName.trim(),
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.flowCreateSuccess"),
      });
      setFlowName("");
      setFlowCode("");
      await loadFlows(selectedScenarioId);
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.flowCreateFailed")),
      });
    }
  };

  const resetFlowForm = () => {
    setSelectedFlowId(null);
    setFlowName("");
    setFlowCode("");
  };

  const handleCreateNode = async () => {
    if (!selectedFlowId || !nodeName.trim() || !nodeCode.trim()) return;
    try {
      const approverConfig = parseNodeApproverConfig();
      await createApprovalNodeApi(selectedFlowId, {
        node_code: nodeCode.trim(),
        node_name: nodeName.trim(),
        node_order: nodes.length + 1,
        node_mode: nodeMode,
        approver_config: approverConfig,
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.nodeCreateSuccess"),
      });
      setNodeName("");
      setNodeCode("");
      setNodes(await listApprovalNodesApi(selectedFlowId));
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: error?.message || String(error || t("approvalPage.nodeCreateFailed")),
      });
    }
  };

  const resetNodeForm = () => {
    setSelectedNodeId(null);
    setNodeName("");
    setNodeCode("");
    setNodeMode("or");
    setNodeApproverConfigText("{}");
  };

  const parseNodeApproverConfig = () => {
    try {
      return JSON.parse(nodeApproverConfigText || "{}");
    } catch (_error) {
      throw new Error(t("approvalPage.approverConfigInvalid"));
    }
  };

  const handleSaveRoute = async () => {
    if (!selectedRouteId || !routeName.trim()) return;
    try {
      await updateApprovalRouteApi(selectedRouteId, {
        route_name: routeName.trim(),
        route_type: routeType,
        flow_definition_id: routeType === "flow" && routeFlowDefinitionId ? Number(routeFlowDefinitionId) : null,
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.routeUpdateSuccess"),
      });
      resetRouteForm();
      if (selectedScenarioId) {
        await loadRoutes(selectedScenarioId);
      }
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.routeUpdateFailed")),
      });
    }
  };

  const handleSaveFlow = async () => {
    if (!selectedFlowId || !flowName.trim() || !flowCode.trim()) return;
    try {
      const currentFlowId = selectedFlowId;
      await updateApprovalFlowApi(selectedFlowId, {
        flow_code: flowCode.trim(),
        flow_name: flowName.trim(),
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.flowUpdateSuccess"),
      });
      const currentScenarioId = selectedScenarioId;
      resetFlowForm();
      if (currentScenarioId) {
        await loadFlows(currentScenarioId);
        setSelectedFlowId(currentFlowId);
      }
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: String(error || t("approvalPage.flowUpdateFailed")),
      });
    }
  };

  const handleSaveNode = async () => {
    if (!selectedNodeId || !nodeName.trim() || !nodeCode.trim()) return;
    try {
      const currentFlowId = selectedFlowId;
      const approverConfig = parseNodeApproverConfig();
      await updateApprovalNodeApi(selectedNodeId, {
        node_code: nodeCode.trim(),
        node_name: nodeName.trim(),
        node_mode: nodeMode,
        approver_config: approverConfig,
      });
      toast({
        title: t("prompt"),
        variant: "success",
        description: t("approvalPage.nodeUpdateSuccess"),
      });
      resetNodeForm();
      if (currentFlowId) {
        setNodes(await listApprovalNodesApi(currentFlowId));
      }
    } catch (error: any) {
      toast({
        title: t("prompt"),
        variant: "error",
        description: error?.message || String(error || t("approvalPage.nodeUpdateFailed")),
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
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => void handleRetryException(item)}
                        className="rounded-lg border border-border-subtle px-3 py-2 text-sm text-text-primary hover:bg-background-primary"
                      >
                        {t("approvalPage.retryAction")}
                      </button>
                      {item.exception_type === "approver_empty" ? (
                        <>
                          <input
                            value={exceptionApproverInputs[item.id] || ""}
                            onChange={(event) =>
                              setExceptionApproverInputs((current) => ({
                                ...current,
                                [item.id]: event.target.value,
                              }))
                            }
                            placeholder={t("approvalPage.approverIdsPlaceholder")}
                            className="h-9 min-w-[200px] rounded-lg border border-border-subtle bg-background-primary px-3 text-sm text-text-primary outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => void handleAssignApprovers(item)}
                            className="rounded-lg border border-border-subtle px-3 py-2 text-sm text-text-primary hover:bg-background-primary"
                          >
                            {t("approvalPage.assignApproversAction")}
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              void handleRetryException(item, {
                                action: "skip_node",
                              })
                            }
                            className="rounded-lg border border-border-subtle px-3 py-2 text-sm text-text-primary hover:bg-background-primary"
                          >
                            {t("approvalPage.skipNodeAction")}
                          </button>
                        </>
                      ) : null}
                    </div>
                  </div>
                  {item.detail && Object.keys(item.detail).length ? (
                    <div className="mt-3 rounded-lg bg-background-primary p-3 text-xs text-text-secondary">
                      {JSON.stringify(item.detail)}
                    </div>
                  ) : null}
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
                    onClick={() => {
                      void loadRoutes(scenario.id);
                      void loadFlows(scenario.id);
                    }}
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
                    <div className="mt-3 flex justify-end">
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleToggleScenario(scenario);
                        }}
                        onKeyDown={(event) => {
                          if (event.key !== "Enter" && event.key !== " ") return;
                          event.preventDefault();
                          event.stopPropagation();
                          void handleToggleScenario(scenario);
                        }}
                        className="rounded-md border border-border-subtle px-3 py-1 text-xs text-text-primary hover:bg-background-main-content"
                      >
                        {scenario.enabled ? t("approvalPage.disableScenario") : t("approvalPage.enableScenario")}
                      </span>
                    </div>
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
            <label className="flex min-w-[200px] flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.routeFlowLabel")}</span>
              <select
                value={routeFlowDefinitionId}
                onChange={(event) => setRouteFlowDefinitionId(event.target.value)}
                disabled={routeType !== "flow"}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none disabled:opacity-60"
              >
                <option value="">{t("approvalPage.routeFlowPlaceholder")}</option>
                {flows.map((flow) => (
                  <option key={flow.id} value={String(flow.id)}>
                    {flow.flow_name || flow.flow_code || `${t("approvalPage.flowFallback")} #${flow.id}`}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!selectedScenarioId || !routeName.trim()}
              onClick={() => void (selectedRouteId ? handleSaveRoute() : handleCreateRoute())}
              className="h-10 rounded-lg bg-primary px-4 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {selectedRouteId ? t("approvalPage.saveRoute") : t("approvalPage.createRoute")}
            </button>
            {selectedRouteId ? (
              <button
                type="button"
                onClick={resetRouteForm}
                className="h-10 rounded-lg border border-border-subtle px-4 text-sm text-text-primary"
              >
                {t("approvalPage.cancelEdit")}
              </button>
            ) : null}
          </div>
          {!routes.length ? (
            <EmptyBlock text={t("approvalPage.emptyRoutes")} />
          ) : (
            <div className="space-y-3">
              {routes.map((route) => (
                <button
                  key={route.id}
                  type="button"
                  onClick={() => {
                    setSelectedRouteId(route.id);
                    setRouteName(route.route_name || "");
                    setRouteType(route.route_type || "flow");
                    setRouteFlowDefinitionId(route.flow_definition_id ? String(route.flow_definition_id) : "");
                  }}
                  className={`w-full rounded-lg border px-4 py-3 text-left ${
                    route.id === selectedRouteId
                      ? "border-primary bg-background-main-content"
                      : "border-border-subtle bg-background-main-content"
                  }`}
                >
                  <div className="text-sm font-medium text-text-primary">
                    {route.route_name || route.route_type || t("approvalPage.routeFallback")} #{route.id}
                  </div>
                  <div className="mt-1 text-xs text-text-secondary">
                    {route.route_type || "--"} · {route.enabled ? t("approvalPage.enabled") : t("approvalPage.disabled")}
                  </div>
                </button>
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_1fr]">
        <SectionCard title={t("approvalPage.flowTitle")} description={t("approvalPage.flowDesc")}>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <label className="flex min-w-[220px] flex-1 flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.flowNameLabel")}</span>
              <input
                value={flowName}
                onChange={(event) => setFlowName(event.target.value)}
                placeholder={t("approvalPage.flowNamePlaceholder")}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              />
            </label>
            <label className="flex min-w-[220px] flex-1 flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.flowCodeLabel")}</span>
              <input
                value={flowCode}
                onChange={(event) => setFlowCode(event.target.value)}
                placeholder={t("approvalPage.flowCodePlaceholder")}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              />
            </label>
            <button
              type="button"
              disabled={!selectedScenarioId || !flowName.trim() || !flowCode.trim()}
              onClick={() => void (selectedFlowId ? handleSaveFlow() : handleCreateFlow())}
              className="h-10 rounded-lg bg-primary px-4 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {selectedFlowId ? t("approvalPage.saveFlow") : t("approvalPage.createFlow")}
            </button>
            {selectedFlowId ? (
              <button
                type="button"
                onClick={resetFlowForm}
                className="h-10 rounded-lg border border-border-subtle px-4 text-sm text-text-primary"
              >
                {t("approvalPage.cancelEdit")}
              </button>
            ) : null}
          </div>
          {!flows.length ? (
            <EmptyBlock text={t("approvalPage.emptyFlows")} />
          ) : (
            <div className="space-y-3">
              {flows.map((flow) => (
                <button
                  key={flow.id}
                  type="button"
                  onClick={async () => {
                    setSelectedFlowId(flow.id);
                    setFlowName(flow.flow_name || "");
                    setFlowCode(flow.flow_code || "");
                    setNodes(await listApprovalNodesApi(flow.id));
                  }}
                  className={`flex w-full flex-col rounded-lg border px-4 py-3 text-left transition-colors ${
                    flow.id === selectedFlowId
                      ? "border-primary bg-background-main-content"
                      : "border-border-subtle bg-background-primary hover:bg-background-main-content"
                  }`}
                >
                  <span className="text-sm font-medium text-text-primary">
                    {flow.flow_name || flow.flow_code || t("approvalPage.flowFallback")}
                  </span>
                  <span className="mt-1 text-xs text-text-secondary">
                    {flow.flow_code || "--"} · {flow.is_active ? t("approvalPage.enabled") : t("approvalPage.disabled")}
                  </span>
                </button>
              ))}
            </div>
          )}
        </SectionCard>

        <SectionCard title={t("approvalPage.nodeTitle")} description={t("approvalPage.nodeDesc")}>
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <label className="flex min-w-[180px] flex-1 flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.nodeNameLabel")}</span>
              <input
                value={nodeName}
                onChange={(event) => setNodeName(event.target.value)}
                placeholder={t("approvalPage.nodeNamePlaceholder")}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              />
            </label>
            <label className="flex min-w-[180px] flex-1 flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.nodeCodeLabel")}</span>
              <input
                value={nodeCode}
                onChange={(event) => setNodeCode(event.target.value)}
                placeholder={t("approvalPage.nodeCodePlaceholder")}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              />
            </label>
            <label className="flex min-w-[160px] flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.nodeModeLabel")}</span>
              <select
                value={nodeMode}
                onChange={(event) => setNodeMode(event.target.value)}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              >
                <option value="or">{t("approvalPage.nodeModeOr")}</option>
                <option value="and">{t("approvalPage.nodeModeAnd")}</option>
              </select>
            </label>
            <label className="flex min-w-[260px] flex-1 flex-col gap-2 text-sm text-text-secondary">
              <span>{t("approvalPage.approverConfigLabel")}</span>
              <input
                value={nodeApproverConfigText}
                onChange={(event) => setNodeApproverConfigText(event.target.value)}
                placeholder={t("approvalPage.approverConfigPlaceholder")}
                className="h-10 rounded-lg border border-border-subtle bg-background-primary px-3 text-text-primary outline-none"
              />
            </label>
            <button
              type="button"
              disabled={!selectedFlowId || !nodeName.trim() || !nodeCode.trim()}
              onClick={() => void (selectedNodeId ? handleSaveNode() : handleCreateNode())}
              className="h-10 rounded-lg bg-primary px-4 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
            >
              {selectedNodeId ? t("approvalPage.saveNode") : t("approvalPage.createNode")}
            </button>
            {selectedNodeId ? (
              <button
                type="button"
                onClick={resetNodeForm}
                className="h-10 rounded-lg border border-border-subtle px-4 text-sm text-text-primary"
              >
                {t("approvalPage.cancelEdit")}
              </button>
            ) : null}
          </div>
          {!nodes.length ? (
            <EmptyBlock text={t("approvalPage.emptyNodes")} />
          ) : (
            <div className="space-y-3">
              {nodes.map((node) => (
                <button
                  key={node.id}
                  type="button"
                  onClick={() => {
                    setSelectedNodeId(node.id);
                    setNodeName(node.node_name || "");
                    setNodeCode(node.node_code || "");
                    setNodeMode(node.node_mode || "or");
                    setNodeApproverConfigText(JSON.stringify(node.approver_config || {}));
                  }}
                  className={`w-full rounded-lg border px-4 py-3 text-left ${
                    node.id === selectedNodeId
                      ? "border-primary bg-background-main-content"
                      : "border-border-subtle bg-background-main-content"
                  }`}
                >
                  <div className="text-sm font-medium text-text-primary">
                    {node.node_name || node.node_code || t("approvalPage.nodeFallback")} #{node.id}
                  </div>
                  <div className="mt-1 text-xs text-text-secondary">
                    {node.node_code || "--"} · {node.node_mode || "--"} · #{node.node_order || "--"}
                  </div>
                </button>
              ))}
            </div>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
