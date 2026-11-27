import { useLocalize } from '~/hooks';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { createBusinessTimeline, recapFromAnswer, type BusinessStep } from './businessTimeline';
import { presentProcess } from './processPresentation';
import { BusinessProcessCard } from './BusinessProcessCard';
import type { AdvisorScene } from './scenes';
interface BusinessTask { id: string; history?: BusinessStep[]; children?: BusinessTask[] }
interface AdvisorLiveProgressProps { scene: AdvisorScene; versionId: string; tasks: BusinessTask[]; steps: BusinessStep[]; status?: string; answer?: string; error?: string; pendingInput?: boolean }

export function AdvisorLiveProgress({ scene, versionId, tasks, steps, status, answer, error, pendingInput }: AdvisorLiveProgressProps) {
  const t = useLocalize();
  const { data: config } = useGetBsConfig();
  const children = config?.tools?.flatMap(group => group.children || []) || [];
  const toolKeys = { procurement: children.find(tool => tool.name === 'query_procurement_history')?.tool_key, transport: children.find(tool => tool.name === 'transport_execute')?.tool_key };
  const engine = createBusinessTimeline(t);
  const state = engine.make(scene, versionId);
  const collect = (rows: BusinessTask[]): BusinessStep[] => rows.flatMap(task => [...(task.history || []), ...collect(task.children || [])]);
  const events = [...steps.map(step => ({ ...step, task_id: step.task_id || versionId })), ...collect(tasks)].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
  events.forEach(event => engine.observe(state, event, toolKeys));
  if (pendingInput) engine.finish(state, { version: 1, mode: 'execution_recap', scene, nodes: [{ title: engine.c('requiredTitle'), summary: engine.c('inputRequested'), status: 'waiting', details: [] }] });
  if (['completed','feedback_completed'].includes(status || '')) {
    const record = recapFromAnswer(answer, scene) || state.transportRecap;
    if (record) engine.finish(state, record);
    else engine.reply(state, !!error || /固定入口未能完成|本次失败|接口失败|取数失败/.test(answer || ''));
  }
  if (error || ['failed','error','terminated','stoped'].includes(status || '')) engine.stop(state, !!error || !['terminated','stoped'].includes(status || ''));
  return <BusinessProcessCard state={presentProcess(state, t)} live />;
}
