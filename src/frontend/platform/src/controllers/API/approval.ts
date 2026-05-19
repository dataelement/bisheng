import axios from "../request";

export interface ApprovalScenarioPreset {
  scenario_code: string;
  scenario_name: string;
  handler_key?: string;
  condition_fields?: string[];
  approver_source_types?: string[];
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
}

export interface ApprovalExceptionItem {
  id: number;
  exception_type: string;
  instance_id?: number;
  status?: string;
  create_time?: string;
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

export async function listApprovalRoutesApi(scenarioId: number): Promise<ApprovalRouteItem[]> {
  return await axios.get(`/api/v1/approval/admin/scenarios/${scenarioId}/routes`);
}

export async function listApprovalExceptionsApi(): Promise<ApprovalExceptionItem[]> {
  return await axios.get("/api/v1/approval/admin/exceptions");
}

export async function retryApprovalExceptionApi(exceptionId: number, action = "retry"): Promise<Record<string, any>> {
  return await axios.post(`/api/v1/approval/admin/exceptions/${exceptionId}/retry`, { action });
}
