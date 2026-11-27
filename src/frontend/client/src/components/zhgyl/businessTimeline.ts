import type { AdvisorScene } from './scenes';
import { readBusinessRecap, type BusinessRecord, type RecapNode, type RecapStatus } from './recapProtocol';

export interface ProcessNode extends RecapNode { id: string }
export interface ProcessState { scene: AdvisorScene; id: string; phase: string; finished: boolean; nodes: ProcessNode[]; failed?: boolean; finalPayload?: BusinessRecord; transportRecap?: BusinessRecord; seen: Set<string>; displaySummary?: string }
export interface BusinessStep { task_id?: string; step_type?: string; name?: string; call_id?: string; status?: string; output?: unknown; timestamp?: number }
type Copy = (key: string, options?: Record<string, unknown>) => string;
const json = (value: unknown): Record<string, unknown> | null => { try { const parsed: unknown = typeof value === 'string' ? JSON.parse(value) : value; return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null; } catch { return null; } };

export function recapFromAnswer(answer: unknown, scene: AdvisorScene | ''): BusinessRecord | null {
  if (typeof answer !== 'string') return null;
  const fence = answer.trimStart().match(/^```(business-process|business)[ \t]*\r?\n([\s\S]{1,30000}?)\r?\n```(?=[ \t]*(?:\r?\n|$))/);
  if (!fence) return null;
  const parsed = readBusinessRecap(fence[2], scene, `language-${fence[1]}`);
  return parsed.kind === 'valid' ? parsed.record : null;
}

/** The D reducer consumes native tool events and bounded result metadata, never reasoning text. */
export function createBusinessTimeline(t: Copy) {
  const c: Copy = (key, options) => t(`zhgyl.flowCopy.${key}`, options);
  const set = (state: ProcessState, id: string, status: RecapStatus, summary: string, details?: string[]) => {
    const node = state.nodes.find(item => item.id === id);
    if (!node) return;
    node.status = status; node.summary = summary; if (details) node.details = details;
  };
  function make(scene: AdvisorScene, id: string): ProcessState {
    const nodes: ProcessNode[] = [
      { id: 'scope', title: c('scope'), summary: c('entering', { scene: c(scene) }), status: 'running', details: [] },
      { id: 'rules', title: c('rules'), summary: c('rulesWaiting'), status: 'pending', details: [] },
    ];
    if (scene === 'procurement') nodes.push({ id: 'query', title: c('query'), summary: c('queryWaiting'), status: 'pending', details: [] });
    nodes.push({ id: 'execute', title: c(scene === 'procurement' ? 'executeProcurement' : scene === 'orders' ? 'executeOrders' : 'executeCosts'), summary: c('executeWaiting'), status: 'pending', details: [] }, { id: 'result', title: c('result'), summary: c('resultWaiting'), status: 'pending', details: [] });
    return { scene, id, phase: 'accepted', finished: false, nodes, seen: new Set() };
  }
  function finish(state: ProcessState, record: BusinessRecord) {
    if (record.scene !== state.scene) return;
    const waiting = record.nodes.some(node => node.status === 'waiting');
    const error = record.nodes.some(node => node.status === 'error');
    const empty = record.nodes.some(node => node.status === 'empty');
    state.finalPayload = record; state.finished = true; state.phase = error ? 'failed' : waiting ? 'waiting' : 'completed';
    set(state, 'scope', 'done', c('scopeProcessed', { scene: c(state.scene) }));
    const rules = state.nodes.find(node => node.id === 'rules');
    if (rules && ['pending','running'].includes(rules.status)) set(state, 'rules', 'skipped', c('rulesNotRead'));
    const query = state.nodes.find(node => node.id === 'query');
    const history = record.nodes.find(node => /核对历史与筛选|核对型号/.test(node.title));
    if (query && history) set(state, 'query', history.status === 'waiting' ? 'empty' : history.status, history.summary, history.details);
    else if (query?.status === 'pending') set(state, 'query', 'skipped', c('queryNotRun'));
    const evidence = record.nodes.filter(node => !/^(理解本轮需求|查看与继续|形成本轮结果)$/.test(node.title)).map(node => `${node.title}：${node.summary}`);
    const match = record.nodes.find(node => /按甲方核验|近似召回|核对查询与匹配/.test(node.title));
    set(state, 'execute', error ? 'error' : waiting ? 'waiting' : empty && !record.nodes.some(node => /^整理/.test(node.title)) ? 'empty' : 'done', error ? c('executeFailed') : waiting ? c('needsInput') : match?.summary || c('executeComplete'), evidence);
    if (!error && !waiting && match) set(state, 'execute', empty && !record.nodes.some(node => /^整理/.test(node.title)) ? 'empty' : 'done', match.summary, evidence);
    set(state, 'result', error ? 'error' : waiting ? 'waiting' : 'done', c(error ? 'resultFailed' : waiting ? 'resultWaitingInput' : 'resultReturned'));
  }
  function observe(state: ProcessState, event: BusinessStep, toolKeys?: { procurement?: string; transport?: string }) {
    if (event.task_id !== state.id || state.finished) return;
    const name = event.name || '';
    if (event.step_type === 'thinking' || name === 'thinking') {
      if (state.phase === 'accepted') { state.phase = 'understanding'; set(state, 'scope', 'running', c('understanding')); }
      return;
    }
    const transport = state.scene === 'transport' && [toolKeys?.transport, 'tool_type_22_631a99bc6670f725c28235e5bf5e4edc'].includes(name);
    const procurement = name === toolKeys?.procurement || name === 'tool_type_21_df150bfcffc4d3a398f68301818e9165';
    if (!transport && !procurement && !['read_file','bisheng_code_interpreter','transport_history','customs_history','write_todos'].includes(name)) return;
    const key = `${event.call_id || name}:${event.status}`;
    if (state.seen.has(key)) return;
    state.seen.add(key);
    set(state, 'scope', 'done', c('entered', { scene: c(state.scene) }));
    if (name === 'read_file') {
      state.phase = event.status === 'start' ? 'loading_rules' : 'planning';
      set(state, 'rules', event.status === 'start' ? 'running' : 'done', c(event.status === 'start' ? 'rulesReading' : 'rulesRead'));
    } else if (name === 'write_todos') { state.phase = 'planning'; set(state, 'scope', 'done', c('planned')); }
    else if (procurement) {
      state.phase = event.status === 'start' ? 'querying' : 'query_returned';
      if (event.status === 'start') set(state, 'query', 'running', c('queryRunning'));
      else {
        const output = json(event.output);
        if (output?.status === 'api_json_saved') set(state, 'query', 'done', c('queryReturned', { count: Number.isInteger(output.totalElements) ? output.totalElements : '', rows: Number.isInteger(output.totalElements) ? c('historyRows') : c('currentData'), more: output.hasNext ? c('paging') : '' }));
        else if (output?.terminal === true) { set(state, 'query', 'error', c('queryFailed')); state.failed = true; }
        else set(state, 'query', 'done', c('queryNeedsValidation'));
      }
    } else {
      if (state.nodes.find(node => node.id === 'rules')?.status === 'pending') set(state, 'rules', 'skipped', c('rulesSkipped'));
      state.phase = event.status === 'start' ? 'executing' : 'validating_result';
      set(state, 'execute', event.status === 'start' || transport ? 'running' : 'done', c(event.status === 'start' ? state.scene === 'procurement' ? 'procurementRunning' : state.scene === 'orders' ? 'ordersRunning' : 'costsRunning' : 'validating'));
      if (event.status !== 'start') {
        const output = json(event.output);
        const record = recapFromAnswer(typeof output?.answer === 'string' ? output.answer : event.output, state.scene);
        if (transport) {
          if (record?.scene === 'transport') state.transportRecap = record;
          set(state, 'execute', 'running', c('transportValidating')); set(state, 'result', 'running', c('transportResult'));
        } else if (record) finish(state, record);
        else set(state, 'result', 'running', c('receiving'));
      }
    }
  }
  function stop(state: ProcessState, failed: boolean) {
    if (state.finished) return;
    state.finished = true; state.phase = failed ? 'failed' : 'stopped';
    state.nodes.forEach(node => { if (node.status === 'running') node.status = failed ? 'error' : 'skipped'; });
    set(state, 'result', failed ? 'error' : 'skipped', c(failed ? 'taskFailed' : 'stopped'));
  }
  function reply(state: ProcessState, failed: boolean) {
    if (state.finished) return;
    if (failed || state.failed) { stop(state, true); return; }
    state.finished = true; state.phase = 'completed';
    state.nodes.forEach(node => { if (!['scope','result'].includes(node.id) && ['pending','running'].includes(node.status)) { node.status = 'skipped'; node.summary = c('unconfirmed'); } });
    set(state, 'scope', 'done', c('replyReturned')); set(state, 'result', 'done', c('replyScope'));
  }
  return { make, observe, finish, stop, reply, c };
}
