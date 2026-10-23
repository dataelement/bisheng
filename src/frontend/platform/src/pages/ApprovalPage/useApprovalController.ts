import { notification } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import {
  createApprovalFlowApi,
  createApprovalRouteApi,
  createApprovalScenarioApi,
  deleteApprovalFlowApi,
  deleteApprovalRouteApi,
  deleteApprovalScenarioApi,
  listApprovalExceptionsApi,
  listApprovalFlowsApi,
  listApprovalNodesApi,
  listApprovalRoutesApi,
  listApprovalScenarioPresetsApi,
  listApprovalScenariosApi,
  reorderApprovalRoutesApi,
  setApprovalFlowNodesApi,
  updateApprovalFlowApi,
  updateApprovalRouteApi,
  updateApprovalScenarioApi,
  type ApprovalExceptionItem,
  type ApprovalFlowItem,
  type ApprovalNodeItem,
  type ApprovalRouteItem,
  type ApprovalScenarioItem,
  type ApprovalScenarioPreset,
} from "@/controllers/API/approval";
import { getRolesApi } from "@/controllers/API/user";
import { showApiError } from "@/controllers/request";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CONDITION_FIELD_META, normalizeApprovalRoles } from "./approvalMetadata";
import { useApprovalExceptions } from "./useApprovalExceptions";

export function useApprovalController() {
  const { t } = useTranslation("bs");

  // ── data ──────────────────────────────────────────────────────────────────
  const [presets, setPresets] = useState<ApprovalScenarioPreset[]>([]);
  const [scenarios, setScenarios] = useState<ApprovalScenarioItem[]>([]);
  const [routes, setRoutes] = useState<ApprovalRouteItem[]>([]);
  const [flows, setFlows] = useState<ApprovalFlowItem[]>([]);
  const [nodes, setNodes] = useState<ApprovalNodeItem[]>([]);
  const [exceptions, setExceptions] = useState<ApprovalExceptionItem[]>([]);
  const [loadError, setLoadError] = useState<unknown>(null);
  // node edit mode: changes are staged locally and only committed via set_flow_nodes (creates a new version)
  const [isNodeEditMode, setIsNodeEditMode] = useState(false);
  const [draftNodes, setDraftNodes] = useState<ApprovalNodeItem[]>([]);
  const [isNodeDirty, setIsNodeDirty] = useState(false);
  const localIdRef = useRef(-1);
  // role_id → role_name map for condition label display
  const [pageRoleNameMap, setPageRoleNameMap] = useState<Record<string, string>>({});
  useEffect(() => {
    getRolesApi("")
      .then((res) => {
        const list = normalizeApprovalRoles(res);
        const map: Record<string, string> = {};
        list.forEach((r) => {
          if (r.id) map[`role_${r.id}`] = r.role_name || `role_${r.id}`;
        });
        setPageRoleNameMap(map);
      })
      .catch(showApiError);
  }, []);

  // ── selection ─────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<"flow" | "exception">("flow");
  const [selectedScenarioId, setSelectedScenarioId] = useState<number | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState<number | null>(null);

  // ── dialog states ─────────────────────────────────────────────────────────
  const [showAddScenario, setShowAddScenario] = useState(false);
  const [editScenarioDialog, setEditScenarioDialog] = useState<{
    open: boolean;
    scenario: ApprovalScenarioItem | null;
    name: string;
  }>({ open: false, scenario: null, name: "" });
  const [routeDialog, setRouteDialog] = useState<{
    open: boolean;
    initial: Partial<ApprovalRouteItem>;
  }>({ open: false, initial: {} });
  const [flowDialog, setFlowDialog] = useState<{
    open: boolean;
    initial: Partial<ApprovalFlowItem>;
  }>({ open: false, initial: {} });
  const [nodeDialog, setNodeDialog] = useState<{
    open: boolean;
    initial: Partial<ApprovalNodeItem>;
  }>({ open: false, initial: {} });
  const [flowPreviewDialog, setFlowPreviewDialog] = useState<{
    open: boolean;
    flowName: string;
    nodes: ApprovalNodeItem[];
  }>({ open: false, flowName: "", nodes: [] });

  // ── exception state ───────────────────────────────────────────────────────
  // exception approver picker dialog state
  const [exceptionPickerOpen, setExceptionPickerOpen] = useState(false);
  const [exceptionPickerItem, setExceptionPickerItem] = useState<ApprovalExceptionItem | null>(null);
  const [exceptionPickerTempIds, setExceptionPickerTempIds] = useState<number[]>([]);
  const [exceptionPickerTempNames, setExceptionPickerTempNames] = useState<string[]>([]);

  // ── computed ──────────────────────────────────────────────────────────────
  const selectedScenario = useMemo(
    () => scenarios.find((s) => s.id === selectedScenarioId) ?? null,
    [scenarios, selectedScenarioId],
  );
  const selectedFlow = useMemo(() => flows.find((f) => f.id === selectedFlowId) ?? null, [flows, selectedFlowId]);
  // condition fields available for the selected scenario (from the preset registry)
  const activeConditionFields = useMemo(() => {
    // applicant_role is universal — every scenario supports identity-based routing.
    // Per PRD §5.4.4, all scenarios include 申请人身份 as a condition field.
    const ALWAYS_INCLUDED = ["applicant_role"];
    const dedup = (arr: string[]) => arr.filter((v, i, self) => self.indexOf(v) === i);
    if (!selectedScenario) {
      return dedup([...ALWAYS_INCLUDED, ...Object.keys(CONDITION_FIELD_META)]);
    }
    const preset = presets.find((p) => p.scenario_code === selectedScenario.scenario_code);
    // Filter preset fields by what CONDITION_FIELD_META knows about;
    // then prepend the always-included fields so they appear first.
    const presetFields = preset?.condition_fields?.filter((f) => CONDITION_FIELD_META[f]) ?? [];
    return dedup([...ALWAYS_INCLUDED, ...presetFields]);
  }, [selectedScenario, presets]);
  // Approver source types allowed for the selected scenario (drives NodeDialog dropdown)
  const activeSourceTypes = useMemo<string[] | undefined>(() => {
    if (!selectedScenario) return undefined;
    const preset = presets.find((p) => p.scenario_code === selectedScenario.scenario_code);
    return preset?.approver_source_types;
  }, [selectedScenario, presets]);
  const existingCodes = useMemo(() => new Set(scenarios.map((s) => s.scenario_code)), [scenarios]);

  // ── data loaders ──────────────────────────────────────────────────────────
  const loadRoutes = async (scenarioId: number) => {
    return await listApprovalRoutesApi(scenarioId);
  };

  const loadFlows = async (scenarioId: number, keepFlowId?: number | null) => {
    const list = await listApprovalFlowsApi(scenarioId);
    const nextId = keepFlowId != null && list.some((f) => f.id === keepFlowId) ? keepFlowId : (list[0]?.id ?? null);
    const nextNodes = nextId ? await listApprovalNodesApi(nextId) : [];
    return { flows: list, selectedFlowId: nextId, nodes: nextNodes };
  };

  const applyFlows = (data: Awaited<ReturnType<typeof loadFlows>>) => {
    setFlows(data.flows);
    setSelectedFlowId(data.selectedFlowId);
    setNodes(data.nodes);
    setIsNodeEditMode(false);
    setDraftNodes([]);
    setIsNodeDirty(false);
  };

  const selectScenario = async (scenarioId: number) => {
    try {
      const [nextRoutes, nextFlows] = await Promise.all([loadRoutes(scenarioId), loadFlows(scenarioId)]);
      setRoutes(nextRoutes);
      applyFlows(nextFlows);
      setSelectedScenarioId(scenarioId);
      setLoadError(null);
    } catch (error) {
      setLoadError(error);
      throw error;
    }
  };

  const loadPage = async () => {
    try {
      const [presetList, scenarioList, exceptionList] = await Promise.all([
        listApprovalScenarioPresetsApi(),
        listApprovalScenariosApi(),
        listApprovalExceptionsApi(),
      ]);
      const initId = selectedScenarioId ?? scenarioList[0]?.id ?? null;
      const scenarioData = initId
        ? await Promise.all([loadRoutes(initId), loadFlows(initId, selectedFlowId)])
        : null;
      setPresets(presetList);
      setScenarios(scenarioList);
      setExceptions(exceptionList);
      if (initId) {
        setSelectedScenarioId(initId);
      }
      if (scenarioData) {
        setRoutes(scenarioData[0]);
        applyFlows(scenarioData[1]);
      }
      setLoadError(null);
    } catch (error) {
      setLoadError(error);
      throw error;
    }
  };

  const initialLoad = useRef(loadPage);
  useEffect(() => {
    void initialLoad.current().catch(showApiError);
  }, []);

  // ── scenario actions ──────────────────────────────────────────────────────
  const handleAddScenario = async (preset: ApprovalScenarioPreset) => {
    try {
      await createApprovalScenarioApi({
        scenario_code: preset.scenario_code,
        scenario_name: preset.scenario_name,
        enabled: false,
      });
      setShowAddScenario(false);
      await loadPage();
    } catch (e) {
      showApiError(e);
    }
  };

  const handleToggleScenario = async (scenario: ApprovalScenarioItem) => {
    try {
      await updateApprovalScenarioApi(scenario.id, { enabled: !scenario.enabled });
      await loadPage();
    } catch (e) {
      showApiError(e);
    }
  };

  const handleSaveScenarioName = async () => {
    const { scenario, name } = editScenarioDialog;
    if (!scenario || !name.trim()) return;
    try {
      await updateApprovalScenarioApi(scenario.id, { scenario_name: name.trim() });
      setEditScenarioDialog({ open: false, scenario: null, name: "" });
      await loadPage();
    } catch (e) {
      showApiError(e);
    }
  };

  const handleDeleteScenario = (scenario: ApprovalScenarioItem) => {
    bsConfirm({
      title: t("approvalPage.deleteScenarioTitle"),
      desc: t("approvalPage.deleteScenarioDesc", { name: scenario.scenario_name }),
      onOk: async (next) => {
        try {
          await deleteApprovalScenarioApi(scenario.id);
          if (selectedScenarioId === scenario.id) setSelectedScenarioId(null);
          await loadPage();
          next();
        } catch (e) {
          showApiError(e);
        }
      },
    });
  };

  // ── route actions ─────────────────────────────────────────────────────────
  const handleSaveRoute = async (data: {
    route_name: string;
    route_type: string;
    flow_definition_id: number | null;
    match_config: { field?: string; value?: string };
  }) => {
    if (!selectedScenarioId) return;
    try {
      const payload = {
        route_name: data.route_name,
        route_type: data.route_type,
        flow_definition_id: data.flow_definition_id,
        match_config: data.match_config,
      };
      if (routeDialog.initial.id) {
        await updateApprovalRouteApi(routeDialog.initial.id, payload);
      } else {
        await createApprovalRouteApi(selectedScenarioId, {
          ...payload,
          sort_order: routes.length,
        });
      }
      setRouteDialog({ open: false, initial: {} });
      setRoutes(await loadRoutes(selectedScenarioId));
    } catch (e) {
      showApiError(e);
    }
  };

  const handleToggleRoute = async (route: ApprovalRouteItem) => {
    try {
      await updateApprovalRouteApi(route.id, {
        route_name: route.route_name,
        route_type: route.route_type,
        flow_definition_id: route.flow_definition_id ?? null,
        enabled: route.enabled === false,
      });
      if (selectedScenarioId) setRoutes(await loadRoutes(selectedScenarioId));
    } catch (e) {
      showApiError(e);
    }
  };

  const handleDeleteRoute = (route: ApprovalRouteItem) => {
    bsConfirm({
      title: t("approvalPage.deleteRouteTitle"),
      desc: t("approvalPage.deleteRouteDesc", { name: route.route_name }),
      onOk: async (next) => {
        try {
          await deleteApprovalRouteApi(route.id);
          if (selectedScenarioId) setRoutes(await loadRoutes(selectedScenarioId));
          next();
        } catch (e) {
          showApiError(e);
        }
      },
    });
  };

  const moveRoute = async (index: number, direction: "up" | "down") => {
    if (!selectedScenarioId) return;
    const next = [...routes];
    const swapIdx = direction === "up" ? index - 1 : index + 1;
    if (swapIdx < 0 || swapIdx >= next.length) return;
    [next[index], next[swapIdx]] = [next[swapIdx], next[index]];
    try {
      await reorderApprovalRoutesApi(
        selectedScenarioId,
        next.map((r) => r.id),
      );
      setRoutes(await loadRoutes(selectedScenarioId));
    } catch (e) {
      showApiError(e);
    }
  };

  // ── flow actions ──────────────────────────────────────────────────────────
  const handleSaveFlow = async (data: { flow_name: string }) => {
    if (!selectedScenarioId) return;
    try {
      let newId = flowDialog.initial.id;
      if (newId) {
        await updateApprovalFlowApi(newId, data);
      } else {
        const created = await createApprovalFlowApi(selectedScenarioId, data);
        newId = created.id;
      }
      setFlowDialog({ open: false, initial: {} });
      applyFlows(await loadFlows(selectedScenarioId, newId));
    } catch (e) {
      showApiError(e);
    }
  };

  const handleDeleteFlow = (flow: ApprovalFlowItem) => {
    bsConfirm({
      title: t("approvalPage.deleteFlowTitle"),
      desc: t("approvalPage.deleteFlowDesc", { name: flow.flow_name }),
      onOk: async (next) => {
        try {
          await deleteApprovalFlowApi(flow.id);
          if (selectedFlowId === flow.id) setSelectedFlowId(null);
          if (selectedScenarioId) applyFlows(await loadFlows(selectedScenarioId));
          next();
        } catch (e) {
          showApiError(e);
        }
      },
    });
  };

  // ── flow preview ─────────────────────────────────────────────────────────
  const handleFlowPreview = async (route: ApprovalRouteItem) => {
    if (!route.flow_definition_id) return;
    const flowName =
      flows.find((f) => f.id === route.flow_definition_id)?.flow_name ??
      t("subjectSearch.flowNumber", { id: route.flow_definition_id });
    try {
      const nodeList = await listApprovalNodesApi(route.flow_definition_id);
      setFlowPreviewDialog({ open: true, flowName, nodes: nodeList });
    } catch (e) {
      showApiError(e);
    }
  };

  // ── node edit mode ────────────────────────────────────────────────────────
  const enterNodeEditMode = () => {
    setDraftNodes([...nodes]);
    setIsNodeDirty(false);
    setIsNodeEditMode(true);
  };

  const cancelNodeEditMode = () => {
    if (isNodeDirty) {
      bsConfirm({
        title: t("approvalPage.discardChangesTitle"),
        desc: t("approvalPage.discardChangesDesc"),
        onOk: (next) => {
          setIsNodeEditMode(false);
          setDraftNodes([]);
          setIsNodeDirty(false);
          next();
        },
      });
    } else {
      setIsNodeEditMode(false);
      setDraftNodes([]);
    }
  };

  const saveNodeChanges = async () => {
    if (!selectedFlowId) return;
    try {
      const payload = draftNodes.map((n, idx) => ({
        node_code: (n.id ?? 0) > 0 ? n.node_code : undefined,
        node_name: n.node_name ?? "",
        node_order: idx + 1,
        node_mode: n.node_mode ?? "or",
        approver_config: n.approver_config ?? {},
      }));
      await setApprovalFlowNodesApi(selectedFlowId, payload);
      const refreshed = await listApprovalNodesApi(selectedFlowId);
      setNodes(refreshed);
      setIsNodeEditMode(false);
      setDraftNodes([]);
      setIsNodeDirty(false);
      notification.open({ type: "success", title: String(t("approvalPage.hint") ?? ''), description: String(t("approvalPage.saveSuccess") ?? '') });
    } catch (e) {
      showApiError(e);
    }
  };

  // ── node actions ──────────────────────────────────────────────────────────
  const handleSaveNode = async (data: {
    node_name: string;
    node_mode: string;
    approver_config: Record<string, unknown>;
  }) => {
    if (!isNodeEditMode || !selectedFlowId) return;
    if (nodeDialog.initial.id) {
      setDraftNodes((prev) => prev.map((n) => (n.id === nodeDialog.initial.id ? { ...n, ...data } : n)));
    } else {
      const localId = localIdRef.current--;
      setDraftNodes((prev) => [
        ...prev,
        {
          id: localId,
          node_name: data.node_name,
          node_order: prev.length + 1,
          node_mode: data.node_mode,
          approver_config: data.approver_config,
        },
      ]);
    }
    setIsNodeDirty(true);
    setNodeDialog({ open: false, initial: {} });
  };

  const moveNode = (index: number, direction: "up" | "down") => {
    if (!isNodeEditMode) return;
    const swapIdx = direction === "up" ? index - 1 : index + 1;
    if (swapIdx < 0 || swapIdx >= draftNodes.length) return;
    const next = [...draftNodes];
    [next[index], next[swapIdx]] = [next[swapIdx], next[index]];
    setDraftNodes(next);
    setIsNodeDirty(true);
  };

  const handleDeleteNode = (node: ApprovalNodeItem) => {
    if (!isNodeEditMode) return;
    setDraftNodes((prev) => prev.filter((n) => n.id !== node.id));
    setIsNodeDirty(true);
  };

  const {
    handleRetryException,
    cancelDialogItem,
    setCancelDialogItem,
    cancelReason,
    setCancelReason,
    handleCancelException,
    toggleExceptionProgress,
    expandedProgressIds,
    loadingProgressId,
    instanceDetailCache,
  } = useApprovalExceptions({ loadPage });

  // ── render ────────────────────────────────────────────────────────────────
  return {
    t,
    setActiveTab,
    loadPage,
    loadError,
    activeTab,
    setShowAddScenario,
    scenarios,
    selectedScenarioId,
    selectScenario,
    setEditScenarioDialog,
    handleDeleteScenario,
    selectedScenario,
    handleToggleScenario,
    setRouteDialog,
    routes,
    pageRoleNameMap,
    flows,
    handleFlowPreview,
    handleToggleRoute,
    moveRoute,
    handleDeleteRoute,
    selectedFlowId,
    isNodeEditMode,
    isNodeDirty,
    setIsNodeEditMode,
    setDraftNodes,
    setIsNodeDirty,
    setSelectedFlowId,
    setNodes,
    selectedFlow,
    setNodeDialog,
    cancelNodeEditMode,
    saveNodeChanges,
    setFlowDialog,
    handleDeleteFlow,
    enterNodeEditMode,
    draftNodes,
    nodes,
    moveNode,
    handleDeleteNode,
    exceptions,
    handleRetryException,
    setExceptionPickerTempIds,
    setExceptionPickerTempNames,
    setExceptionPickerItem,
    setExceptionPickerOpen,
    setCancelDialogItem,
    setCancelReason,
    toggleExceptionProgress,
    expandedProgressIds,
    loadingProgressId,
    instanceDetailCache,
    showAddScenario,
    presets,
    existingCodes,
    handleAddScenario,
    routeDialog,
    activeConditionFields,
    handleSaveRoute,
    flowDialog,
    handleSaveFlow,
    nodeDialog,
    activeSourceTypes,
    handleSaveNode,
    flowPreviewDialog,
    setFlowPreviewDialog,
    editScenarioDialog,
    handleSaveScenarioName,
    exceptionPickerOpen,
    exceptionPickerTempIds,
    exceptionPickerTempNames,
    exceptionPickerItem,
    cancelDialogItem,
    cancelReason,
    handleCancelException,
  };
}
