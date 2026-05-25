import axios from "../request";

export interface ApprovalConditionFieldOption {
  value: string;
  label: string;
}

export interface ApprovalConditionFieldDescriptor {
  field: string;
  label?: string;
  type?: "text" | "select" | "selector" | string;
  values?: ApprovalConditionFieldOption[];
  selector_type?: string | null;
}

export interface ApprovalScenarioPreset {
  scenario_code: string;
  scenario_name: string;
  handler_key?: string;
  condition_fields?: Array<string | ApprovalConditionFieldDescriptor>;
  approver_source_types?: string[];
  condition_field_options?: ApprovalConditionFieldDescriptor[];
  approver_source_options?: Array<{
    source_type: string;
    label: string;
  }>;
}

export interface ApprovalScenarioItem {
  id: number;
  scenario_code: string;
  scenario_name: string;
  enabled?: boolean;
}

export interface ApprovalRouteItem {
  id: number;
  route_type?: string;
  route_name?: string;
  enabled?: boolean;
  flow_definition_id?: number | null;
  match_config?: { field?: string; value?: string } | null;
}

export interface ApprovalFlowItem {
  id: number;
  flow_code?: string;
  flow_name?: string;
  is_active?: boolean;
}

export interface ApprovalNodeItem {
  id: number;
  node_code?: string;
  node_name?: string;
  node_order?: number;
  node_mode?: string;
  approver_config?: Record<string, any>;
}

export interface ApprovalExceptionItem {
  id: number;
  exception_type: string;
  instance_id?: number;
  status?: string;
  create_time?: string;
  detail?: Record<string, any>;
  error_summary?: string | null;
  // enriched from instance
  business_name?: string | null;
  scenario_name?: string | null;
  scenario_code?: string | null;
  applicant_user_name?: string | null;
}

export interface ApprovalInstanceDetail {
  instance_id?: number;
  status?: string;
  flow_nodes?: {
    node_code?: string;
    node_name?: string;
    node_order?: number;
    node_mode?: string;
    task_id?: number;
    status?: string;
  }[];
  tasks?: {
    task_id?: number;
    id?: number;
    approver_user_name?: string;
    node_name?: string;
    node_order?: number;
    status?: string;
    comment?: string;
    update_time?: string;
  }[];
  action_logs?: {
    id?: number;
    action?: string;
    operator_user_name?: string;
    create_time?: string;
    detail?: Record<string, any>;
  }[];
}

export async function listApprovalScenarioPresetsApi(): Promise<ApprovalScenarioPreset[]> {
  return await axios.get("/api/v1/approval/admin/scenario-presets");
}

export async function listApprovalScenariosApi(): Promise<ApprovalScenarioItem[]> {
  return await axios.get("/api/v1/approval/admin/scenarios");
}

export async function createApprovalScenarioApi(data: {
  scenario_code: string;
  scenario_name: string;
  enabled?: boolean;
}): Promise<ApprovalScenarioItem> {
  return await axios.post("/api/v1/approval/admin/scenarios", data);
}

export async function updateApprovalScenarioApi(
  scenarioId: number,
  data: {
    scenario_name?: string;
    enabled?: boolean;
    display_name?: string | null;
  },
): Promise<ApprovalScenarioItem> {
  return await axios.put(`/api/v1/approval/admin/scenarios/${scenarioId}`, data);
}

export async function listApprovalRoutesApi(scenarioId: number): Promise<ApprovalRouteItem[]> {
  return await axios.get(`/api/v1/approval/admin/scenarios/${scenarioId}/routes`);
}

export async function createApprovalRouteApi(
  scenarioId: number,
  data: {
    route_name: string;
    route_type: string;
    sort_order?: number;
    flow_definition_id?: number | null;
    match_config?: Record<string, any>;
  },
): Promise<ApprovalRouteItem> {
  return await axios.post(`/api/v1/approval/admin/scenarios/${scenarioId}/routes`, data);
}

export async function updateApprovalRouteApi(
  routeRuleId: number,
  data: {
    route_name?: string;
    route_type?: string;
    sort_order?: number;
    flow_definition_id?: number | null;
    match_config?: Record<string, any>;
    enabled?: boolean;
  },
): Promise<ApprovalRouteItem> {
  return await axios.put(`/api/v1/approval/admin/routes/${routeRuleId}`, data);
}

export async function listApprovalExceptionsApi(): Promise<ApprovalExceptionItem[]> {
  return await axios.get("/api/v1/approval/admin/exceptions");
}

export async function listApprovalFlowsApi(scenarioId: number): Promise<ApprovalFlowItem[]> {
  return await axios.get(`/api/v1/approval/admin/scenarios/${scenarioId}/flows`);
}

export async function createApprovalFlowApi(
  scenarioId: number,
  data: {
    flow_name: string;
    is_active?: boolean;
  },
): Promise<ApprovalFlowItem> {
  return await axios.post(`/api/v1/approval/admin/scenarios/${scenarioId}/flows`, data);
}

export async function updateApprovalFlowApi(
  flowDefinitionId: number,
  data: {
    flow_name?: string;
    is_active?: boolean;
  },
): Promise<ApprovalFlowItem> {
  return await axios.put(`/api/v1/approval/admin/flows/${flowDefinitionId}`, data);
}

export async function listApprovalNodesApi(flowDefinitionId: number): Promise<ApprovalNodeItem[]> {
  return await axios.get(`/api/v1/approval/admin/flows/${flowDefinitionId}/nodes`);
}


export async function deleteApprovalScenarioApi(scenarioId: number): Promise<void> {
  return await axios.delete(`/api/v1/approval/admin/scenarios/${scenarioId}`);
}

export async function deleteApprovalRouteApi(routeRuleId: number): Promise<void> {
  return await axios.delete(`/api/v1/approval/admin/routes/${routeRuleId}`);
}

export async function reorderApprovalRoutesApi(
  scenarioId: number,
  orderedRouteIds: number[],
): Promise<void> {
  return await axios.patch(
    `/api/v1/approval/admin/scenarios/${scenarioId}/routes/reorder`,
    { ordered_route_ids: orderedRouteIds },
  );
}

export async function deleteApprovalFlowApi(flowDefinitionId: number): Promise<void> {
  return await axios.delete(`/api/v1/approval/admin/flows/${flowDefinitionId}`);
}

export async function setApprovalFlowNodesApi(
  flowDefinitionId: number,
  nodes: {
    node_code?: string;
    node_name: string;
    node_order: number;
    node_mode: string;
    approver_config?: Record<string, any>;
    extra_config?: Record<string, any>;
  }[],
): Promise<{ flow_version_id: number; version_no: number; nodes: ApprovalNodeItem[] }> {
  return await axios.put(`/api/v1/approval/admin/flows/${flowDefinitionId}/nodes`, { nodes });
}


export async function retryApprovalExceptionApi(
  exceptionId: number,
  payload: {
    action?: string;
    approver_user_ids?: number[];
  } = {},
): Promise<Record<string, any>> {
  return await axios.post(`/api/v1/approval/admin/exceptions/${exceptionId}/retry`, {
    action: payload.action ?? "retry",
    approver_user_ids: payload.approver_user_ids ?? [],
  });
}

export async function cancelApprovalExceptionApi(
  exceptionId: number,
  reason: string,
): Promise<Record<string, any>> {
  return await axios.post(`/api/v1/approval/admin/exceptions/${exceptionId}/cancel`, { reason });
}

export async function applyMenuAccessApi(data: {
  menu_key: string;
  menu_name: string;
  reason?: string;
}): Promise<Record<string, any>> {
  return await axios.post(`/api/v1/approval/menu-access/apply`, data);
}

export async function getApprovalInstanceDetailForAdminApi(instanceId: number): Promise<ApprovalInstanceDetail> {
  return await axios.get(`/api/v1/approval/instances/${instanceId}`);
}
