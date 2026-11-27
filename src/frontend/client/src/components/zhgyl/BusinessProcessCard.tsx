import { useLocalize } from '~/hooks';
import type { ProcessState } from './businessTimeline';
import { readableProcessDetail } from './processPresentation';
const marks = { done:'✓', running:'•', waiting:'?', pending:'·', error:'!', empty:'−', skipped:'–' };

export function BusinessProcessCard({ state, live = false }: { state: ProcessState; live?: boolean }) {
  const t = useLocalize();
  const title = `${t(`zhgyl.scenes.${state.scene}.label`)} · ${t(live ? 'zhgyl.flowCopy.executionFlow' : 'zhgyl.flowCopy.executionRecord')}`;
  const summary = live ? state.displaySummary || t(`zhgyl.flowCopy.${state.finished ? state.phase === 'waiting' ? 'waitingSummary' : state.phase === 'failed' ? 'failedSummary' : state.phase === 'stopped' ? 'stoppedSummary' : 'completedSummary' : 'liveSummary'}`) : t('zhgyl.flowCopy.historySummary');
  return <details open className={`zh-process${live ? ' zh-sop-live' : ' zh-historical-process'}`} data-scene={state.scene} data-sop-id={state.id || undefined} data-sop-phase={state.phase} aria-label={title}>
    <summary><strong>{title}</strong><small>{summary}</small></summary>
    <div className="zh-process-intro">{t(live ? 'zhgyl.flowCopy.liveIntro' : 'zhgyl.flowCopy.historyIntro')}{state.finalPayload?.demo && <span className="zh-process-demo">{t('zhgyl.recapDemo')}</span>}</div>
    {state.nodes.map(node => <details className="zh-node" data-state={node.status} data-node-id={node.id} key={node.id}>
      <summary><span className="zh-node-icon">{marks[node.status]}</span><span className="zh-node-copy"><b>{node.title}</b><span>{node.summary}</span></span><span className="zh-node-state">{t(`zhgyl.recapStates.${node.status}`)}</span></summary>
      {!!node.details.length && <div className="zh-node-detail">{node.details.map((detail,index) => <div key={index}>{readableProcessDetail(detail, state.scene, t)}</div>)}</div>}
    </details>)}<div className="zh-process-footer" />
  </details>;
}
