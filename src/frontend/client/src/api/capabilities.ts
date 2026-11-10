import request from './request';

export type CapabilityKind = 'skill' | 'builtin' | 'api' | 'mcp';
export interface Capability {
  id: string;
  resource_id: number;
  kind: CapabilityKind;
  name: string;
  tool_key?: string | null;
  description: string;
  provider: string;
  ready: boolean;
  availability_enabled?: boolean | null;
  demo: boolean;
  invocation_name: string;
  trial: { scenario: 'time' | 'order' | 'inventory'; arguments: Record<string, string> } | null;
}
export interface CapabilityResult {
  tool_id: number;
  result: unknown;
  elapsed_ms: number;
  demo_data: boolean;
}
interface Envelope<T> { status_code: number; data: T }
export async function getCapabilities(): Promise<Capability[]> {
  const response = await request.get<Envelope<{ items: Capability[] }>>('/api/v1/dsh/capabilities');
  if (response.status_code !== 200 || !Array.isArray(response.data?.items)) throw new Error('Capability catalog unavailable');
  return response.data.items;
}
export async function runCapabilityTrial(id: number, args: Record<string, string>): Promise<CapabilityResult> {
  const response = await request.post(`/api/v1/dsh/capabilities/${id}/trial`, { arguments: args }) as Envelope<CapabilityResult>;
  if (response.status_code !== 200) throw new Error('Capability trial failed');
  return response.data;
}

export async function setCapabilityAvailability(id: number, enabled: boolean): Promise<void> {
  const response = await request.put(`/api/v1/dsh/capabilities/${id}/availability`, { enabled }) as Envelope<unknown>;
  if (response.status_code !== 200) throw new Error('Capability availability update failed');
}
