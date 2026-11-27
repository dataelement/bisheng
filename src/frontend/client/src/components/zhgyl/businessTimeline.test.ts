import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import zh from '../../locales/zh-Hans/translation.json';
import { createBusinessTimeline, type BusinessStep, type ProcessState } from './businessTimeline';
import { presentProcess } from './processPresentation';
import type { AdvisorScene } from './scenes';
import type { BusinessRecord } from './recapProtocol';

const reference = runInNewContext(`${readFileSync(join(__dirname, 'fixtures/d-timeline-engine.txt'), 'utf8')}\n({ engine: ZhSopState, presentation: ZhUnifiedTimeline })`) as { engine: { make: (scene: string, id: string) => ProcessState; observe: (state: ProcessState, event: BusinessStep) => void; finish: (state: ProcessState, record: BusinessRecord) => void; stop: (state: ProcessState, failed: boolean) => void; reply: (state: ProcessState, failed: boolean) => void }; presentation: { present: (state: ProcessState) => ProcessState } };
const dictionary = zh.zhgyl.flowCopy as Record<string, string>;
const t = (key: string, options?: Record<string, unknown>) => (dictionary[key.replace('zhgyl.flowCopy.', '')] || key).replace(/{{([^}]+)}}/g, (_, name: string) => String(options?.[name] ?? ''));
const engine = createBusinessTimeline(t);
const snapshot = (state: ProcessState) => JSON.parse(JSON.stringify({ phase: state.phase, finished: state.finished, nodes: state.nodes }));
const id = 'synthetic-session-version';
const names = { procurement:'tool_type_21_df150bfcffc4d3a398f68301818e9165', transport:'tool_type_22_631a99bc6670f725c28235e5bf5e4edc', customs:'bisheng_code_interpreter', orders:'bisheng_code_interpreter' };

test.each<AdvisorScene>(['procurement','transport','customs','orders'])('matches D initial, live event, stop and reply states: %s', scene => {
  const old = reference.engine.make(scene, id); const next = engine.make(scene, id);
  expect(snapshot(next)).toEqual(snapshot(old));
  const events: BusinessStep[] = [
    { task_id:id, step_type:'thinking', name:'thinking', status:'start' },
    { task_id:id, name:'read_file', status:'start', call_id:'rules' },
    { task_id:id, name:'read_file', status:'end', call_id:'rules' },
    { task_id:id, name:names[scene], status:'start', call_id:'query' },
    { task_id:id, name:names[scene], status:'end', call_id:'query', output:JSON.stringify({ status:'api_json_saved', totalElements:5, hasNext:true }) },
  ];
  for (const event of events) { reference.engine.observe(old, event); engine.observe(next, event); expect(snapshot(next)).toEqual(snapshot(old)); }
  reference.engine.reply(old, false); engine.reply(next, false); expect(snapshot(next)).toEqual(snapshot(old));
  const stoppedOld = reference.engine.make(scene,id); const stoppedNew = engine.make(scene,id);
  reference.engine.stop(stoppedOld,true); engine.stop(stoppedNew,true); expect(snapshot(stoppedNew)).toEqual(snapshot(stoppedOld));
});

test.each<AdvisorScene>(['procurement','transport','customs','orders'])('matches D final business recap and unified presentation: %s', scene => {
  const titles = zh.zhgyl.flowCopy;
  const record: BusinessRecord = { version:1, mode:'execution_recap', scene, nodes:[{ title:titles.understandTitle, summary:'Synthetic query', status:'done', details:[] }, { title:titles.requiredTitle, summary:'Synthetic input', status:'waiting', details:[] }] };
  const old = reference.engine.make(scene,id); const next = engine.make(scene,id);
  reference.engine.finish(old, record); engine.finish(next, record);
  expect(snapshot(next)).toEqual(snapshot(old));
  expect(snapshot(presentProcess(next,t))).toEqual(snapshot(reference.presentation.present(old)));
});

test('ignores other tasks and duplicate tool frames, as D does', () => {
  const old = reference.engine.make('customs',id); const next = engine.make('customs',id);
  for (const event of [{task_id:'other',name:'read_file',status:'end'}, {task_id:id,name:'read_file',status:'end'}, {task_id:id,name:'read_file',status:'end'}]) { reference.engine.observe(old,event); engine.observe(next,event); }
  expect(snapshot(next)).toEqual(snapshot(old));
});
