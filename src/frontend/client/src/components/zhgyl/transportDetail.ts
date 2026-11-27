const marker = /(?:\r?\n){2}<transport_detail_v1>[^\r\n]*<\/transport_detail_v1>\s*$/;
export function stripTransportDetail(text: string): string { return text.replace(marker, ''); }
export function transportReference(text: string): string | null {
  return stripTransportDetail(text).trim().match(/^(?:请\s*)?(?:查看|查一下|看看|查)\s*(F\d{2,})\s*(?:的\s*)?(?:账单\s*)?详情[。.!！?？]?$/i)?.[1]?.toUpperCase() || stripTransportDetail(text).trim().match(/^(?:view|show)\s+(F\d{2,})\s+(?:bill\s+)?details[.!?]?$/i)?.[1]?.toUpperCase() || stripTransportDetail(text).trim().match(/^(F\d{2,})\s*の詳細を表示[。.!！?？]?$/i)?.[1]?.toUpperCase() || null;
}
export interface TransportStep { step_type?: string; name?: string; status?: string; output?: unknown }
export interface TransportTask { history?: TransportStep[]; children?: TransportTask[] }
export interface TransportVersion { id: string; session_id?: string; skills?: string[]; status?: string; question?: string; tools?: { children?: { tool_key?: string }[] }[] }
interface Binding { contextId: string; queryId: string }
const steps = (tasks: TransportTask[]): TransportStep[] => tasks.flatMap(task => [...(task.history || []), ...steps(task.children || [])]);

export async function resolveTransportBinding(chatId: string, toolKey: string, versions: TransportVersion[], getTasks: (id: string) => Promise<TransportTask[]>): Promise<Binding | null> {
  for (const version of versions) {
    if (version.session_id !== chatId || !version.skills?.includes('transport-native-api')) continue;
    if (version.status !== 'completed' || !version.tools?.some(group => group.children?.some(tool => tool.tool_key === toolKey))) return null;
    const calls = steps(await getTasks(version.id)).filter(step => step.step_type === 'tool' && step.name === toolKey && step.status === 'end');
    if (calls.length === 0 && transportReference(version.question || '')) continue;
    if (calls.length !== 1) return null;
    const output = (typeof calls[0].output === 'string' ? JSON.parse(calls[0].output) : calls[0].output) as Record<string, unknown> | null;
    if (output?.protocol !== 'transport-fixed-entry-v1' || output.terminal !== true || output.outcome !== 'ok' || !/^[a-f0-9]{48}$/.test(String(output.context_id || '')) || !/^[a-f0-9]{12}$/.test(String(output.query_id || ''))) return null;
    return { contextId: String(output.context_id), queryId: String(output.query_id) };
  }
  return null;
}
export function transportPayload(text: string, reference: string, binding: Binding): string {
  return `${stripTransportDetail(text)}\n\n<transport_detail_v1>${JSON.stringify({ request_json: JSON.stringify({ action: 'detail', reference, query_id: binding.queryId }), context_id: binding.contextId })}</transport_detail_v1>`;
}
