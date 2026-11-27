import type { BusinessRecord, RecapNode } from './recapProtocol';
import type { ProcessNode, ProcessState } from './businessTimeline';
type Copy = (key: string, options?: Record<string, unknown>) => string;
const priority = (title: string) => /^理解本轮需求$/.test(title) ? 0 : /核对必要条件|未完成/.test(title) ? 1 : /^核对查询与匹配$/.test(title) ? 2 : /^核对参考强度$/.test(title) ? 3 : /^核对费用与完整覆盖$/.test(title) ? 4 : /^整理/.test(title) ? 5 : 6;
const clone = (node: RecapNode, id: string): ProcessNode => ({ ...node, id, details: [...node.details] });

export function presentProcess(state: ProcessState, t: Copy): ProcessState {
  if (!['transport','customs'].includes(state.scene)) return state;
  const record = state.finalPayload;
  const source = record?.nodes || [];
  const waiting = source.some(node => node.status === 'waiting') || state.phase === 'waiting';
  const error = source.some(node => node.status === 'error') || state.phase === 'failed';
  const match = source.find(node => /^核对查询与匹配$/.test(node.title));
  const empty = match?.status === 'empty';
  const nodes = state.nodes.map(node => clone(node, node.id));
  const scope = nodes.find(node => node.id === 'scope');
  const rules = nodes.find(node => node.id === 'rules');
  const execute = nodes.find(node => node.id === 'execute');
  const result = nodes.find(node => node.id === 'result');
  if (scope) scope.title = t('zhgyl.flowCopy.understandTitle');
  if (rules) rules.title = t('zhgyl.flowCopy.sceneRules', { scene: t(`zhgyl.flowCopy.${state.scene}`) });
  if (record) {
    const request = source.find(node => /^理解本轮需求$/.test(node.title));
    if (scope && request) { scope.summary = request.summary; scope.details = [...(record.conditions || request.details)]; }
    const actual = source.find(node => /^核对必要条件$/.test(node.title)) || source.find(node => node.status === 'error') || match || source.find(node => /^核对数据边界$/.test(node.title));
    if (execute && actual) Object.assign(execute, clone(actual, 'execute'));
    const extras = source.filter(node => /^核对参考强度$|^核对费用与完整覆盖$|^整理/.test(node.title)).map((node, index) => clone(node, `evidence-${index}`)).sort((a, b) => priority(a.title) - priority(b.title));
    extras.forEach(node => { if (/^核对费用与完整覆盖$/.test(node.title) && node.details.some(text => /不自动分摊|不分摊/.test(text))) node.summary += t('zhgyl.flowCopy.unallocated'); });
    const at = result ? nodes.indexOf(result) : nodes.length;
    nodes.splice(at, 0, ...extras);
    if (result && empty) result.summary = t('zhgyl.flowCopy.noMatch');
  }
  const displaySummary = t(`zhgyl.flowCopy.${error ? 'failedSummary' : state.phase === 'stopped' ? 'stoppedSummary' : waiting ? 'waitingSummary' : empty ? 'emptySummary' : state.finished ? 'completedSummary' : 'liveSummary'}`);
  return { ...state, nodes, displaySummary };
}

export function historicalProcess(record: BusinessRecord): ProcessState {
  const nodes = record.nodes.map((node, index) => clone(node, `receipt-${index}`));
  if (['transport','customs'].includes(record.scene)) nodes.sort((a, b) => priority(a.title) - priority(b.title));
  return { scene: record.scene, id: '', phase: 'historical', finished: true, nodes, seen: new Set(), finalPayload: record };
}

export function readableProcessDetail(text: string, scene: string, t: Copy): string {
  if (/^生效筛选：/.test(text)) {
    try {
      const fields = JSON.parse(text.slice(5)) as Record<string, unknown>;
      const entries = Object.entries(fields);
      const aliases: Record<string, string> = { date_from:'dateFrom', date_to:'dateTo', currency:'currency', unit:'unit', trade_term:'tradeTerm', trade_place:'tradePlace', supplier:'supplier', supplier_name:'supplier', supplier_contains:'supplierContains', customer:'customer', customer_contains:'customerContains' };
      return t('zhgyl.flowCopy.effectiveFilters') + (entries.length ? entries.map(([key,value]) => `${t(`zhgyl.flowCopy.${aliases[key] || 'extraCondition'}`)} ${Array.isArray(value) ? value.join('、') : String(value)}`).join('；') : t('zhgyl.flowCopy.noFilters'));
    } catch { return text; }
  }
  if (/^逐级匹配步骤：/.test(text)) {
    try {
      const rows = JSON.parse(text.slice(7)) as { criterion: string; before: number; after: number; decision: string }[];
      if (!rows.length) return t('zhgyl.flowCopy.noRelaxation');
      const aliases: Record<string,string> = { material:'material', weight:'grossWeight', size:'packageSize', quantity:'packageCount' };
      return `${t('zhgyl.flowCopy.matchSteps')}\n${rows.map(row => `${t(`zhgyl.flowCopy.${aliases[row.criterion] || 'currentCondition'}`)}：${row.before} → ${row.after}${t('zhgyl.flowCopy.rows')}；${t(`zhgyl.flowCopy.${row.decision === 'keep_previous' ? 'keepPrevious' : 'sameCondition'}`)}`).join('\n')}`;
    } catch { return t('zhgyl.flowCopy.matchDetails'); }
  }
  return text;
}
