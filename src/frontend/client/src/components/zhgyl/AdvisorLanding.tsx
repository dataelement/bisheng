import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import { advisorScenes, type WorkspaceScene } from './scenes';
import { selectAdvisorPlaceholder } from './advisorDraft';
import { AdvisorIcon, AdvisorTaskIcon } from './AdvisorIcons';
import './workspace.css';

interface AdvisorLandingProps {
  scene: WorkspaceScene;
  ready: boolean;
  error: boolean;
  onRetry: () => void;
  onStarterClick?: (text: string) => void;
  orderContext?: ReactNode;
  orderNumber?: string;
}

export function AdvisorLanding({ scene, ready, error, onRetry, onStarterClick, orderContext, orderNumber }: AdvisorLandingProps) {
  const t = useLocalize();
  const selected = scene && scene !== 'select';
  if (!selected) return <section className="assistant-home" data-testid="assistant-chooser">
    <header className="assistant-home-heading">
      <div className="assistant-home-eyebrow"><span aria-hidden="true" />{t('zhgyl.workspace')}</div>
      <h2>{t('zhgyl.title')}</h2><p>{t('zhgyl.subtitle')}</p>
      <div className="flight-lights" aria-hidden="true"><i /><i /><i /></div>
    </header>
    <div className="assistant-home-grid">
      {advisorScenes.filter(key => key !== 'orders').map(key => {
        const features = t(`zhgyl.scenes.${key}.home.features`, { returnObjects: true }) as unknown as string[];
        return <Link key={key} to={`/c/new?agent=${key}`} className="assistant-home-card" title={features.join(' · ')} data-testid={`choose-${key}`}>
          <div className="assistant-home-card-top"><span className="assistant-home-icon"><AdvisorIcon scene={key} /></span></div>
          <h3>{t(`zhgyl.scenes.${key}.label`)}</h3><p>{t(`zhgyl.scenes.${key}.home.desc`)}</p>
          <div className="zh-capabilities">{features.map((feature, index) => <div key={index}><span className="zh-cap-dot">{String(index + 1).padStart(2, '0')}</span><span>{feature}</span></div>)}</div>
          <div className="zh-home-example"><small>{t('zhgyl.example')}</small><span>{t(`zhgyl.scenes.${key}.home.example`)}</span></div>
          <div className="zh-home-action">{t(`zhgyl.scenes.${key}.home.action`)} →</div>
        </Link>;
      })}
    </div>
    <div className="assistant-home-general"><span />{t('zhgyl.generalEntry')}<span /></div>
  </section>;
  return <div className="assistant-chat-intro" data-order-breadcrumb={t('zhgyl.orderBreadcrumb')}>
    <AdvisorHeading scene={scene} />
    {orderContext}
    <AdvisorOpening scene={scene} ready={ready} error={error} onRetry={onRetry} onStarterClick={onStarterClick} orderNumber={orderNumber} />
  </div>;
}

interface AdvisorOpeningProps extends Omit<AdvisorLandingProps, 'scene'> { scene: Exclude<WorkspaceScene, 'select' | ''>; compact?: boolean }

export function AdvisorOpening({ scene, ready, error, onRetry, onStarterClick, orderNumber, compact = false }: AdvisorOpeningProps) {
  const t = useLocalize();
  const [selected, setSelected] = useState<number | null>(null);
  const chosen = useRef('');
  useEffect(() => { setSelected(null); chosen.current = ''; }, [scene]);
  useEffect(() => {
    let frame = 0;
    const handleEdited = (event: Event) => {
      if (!(event.target instanceof Element) || !event.target.closest(`[data-assistant-scene="${scene}"] [data-testid="ai-chat-input"]`)) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const editor = document.querySelector(`[data-assistant-scene="${scene}"] [data-testid="ai-chat-input"]`);
        if (chosen.current && !(editor?.textContent || '').includes(chosen.current)) { chosen.current = ''; setSelected(null); }
      });
    };
    document.addEventListener('input', handleEdited, true);
    return () => { document.removeEventListener('input', handleEdited, true); cancelAnimationFrame(frame); };
  }, [scene]);
  const baseParagraphs = t(`zhgyl.scenes.${scene}.paragraphs`, { returnObjects: true }) as unknown as string[];
  const baseExamples = t(`zhgyl.scenes.${scene}.examples`, { returnObjects: true }) as unknown as { label: string; description: string; text: string; icon?: string }[];
  const linked = !compact && scene === 'orders' && !!orderNumber;
  const paragraphs = linked ? [t('zhgyl.orderLinkedIntro', { order: orderNumber }), t('zhgyl.orderLinkedAsk'), t('zhgyl.orderLinkedConfirm')] : baseParagraphs;
  const examples = linked ? baseExamples.map((example, index) => ({ ...example,
    label: t(['zhgyl.orderLinkedOverview','zhgyl.orderLinkedDelivery','zhgyl.orderLinkedReminder'][index]),
    description: index === 1 ? t('zhgyl.orderLinkedDeliveryDescription') : example.description,
    text: t(['zhgyl.orderLinkedOverviewQuestion','zhgyl.orderLinkedDeliveryQuestion','zhgyl.orderLinkedReminderQuestion'][index], { order: orderNumber }),
  })) : baseExamples;
  const emphasis = t(linked ? 'zhgyl.orderLinkedEmphasis' : `zhgyl.scenes.${scene}.emphasis`);
  const handleFill = (text: string, index: number) => {
    if (!ready || compact) return;
    chosen.current = text; setSelected(index); onStarterClick?.(text);
    requestAnimationFrame(() => requestAnimationFrame(() => selectAdvisorPlaceholder(scene)));
  };
  return <article className={`assistant-opening assistant-friendly${compact ? ' assistant-opening-history' : ''}`} data-testid={`${scene}-welcome`} aria-label={t('zhgyl.openingLabel', { label: t(`zhgyl.scenes.${scene}.label`) })}>
    <span className="assistant-avatar" aria-hidden="true"><AdvisorIcon scene={scene} /></span>
    <div className="assistant-opening-body">
      <div className="assistant-message-name">{t(`zhgyl.scenes.${scene}.label`)}<span>{t('zhgyl.guide')}</span>{compact && <Link to={scene === 'orders' ? '/c/new?module=order-tracking' : '/c/new'}>{t(scene === 'orders' ? 'zhgyl.backOrders' : 'zhgyl.switch')}</Link>}</div>
      {(compact ? paragraphs.slice(0, 1) : paragraphs).map((text, index) => {
        const at = emphasis ? text.indexOf(emphasis) : -1;
        return <p className="assistant-friendly-paragraph" key={index}>{at < 0 ? text : <>{text.slice(0, at)}<strong>{emphasis}</strong>{text.slice(at + emphasis.length)}</>}</p>;
      })}
      {!compact && <div className="assistant-friendly-tasks" data-example-label={t('zhgyl.example')} aria-label={t('zhgyl.quickTasks', { label: t(`zhgyl.scenes.${scene}.label`) })}>
        {examples.map((example, index) => <button type="button" disabled={!ready} key={index} data-testid={`${scene}-task-${index}`} aria-label={t('zhgyl.fillQuestion', { label: example.label })} aria-pressed={selected === index} onClick={() => handleFill(example.text, index)}>
          <AdvisorTaskIcon type={example.icon || 'search'} /><span className="assistant-friendly-task-copy"><strong>{example.label}</strong><small>{example.description}</small></span>
          <svg className="assistant-friendly-chevron" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg>
        </button>)}
      </div>}
      {!compact && !ready && <div className="assistant-status" role={error ? 'alert' : 'status'}>{t(error ? 'zhgyl.unavailable' : 'zhgyl.ready')}{error && <button type="button" onClick={onRetry}>{t('zhgyl.retry')}</button>}</div>}
    </div>
  </article>;
}

export function AdvisorHeading({ scene, actions, title }: { scene: WorkspaceScene; actions?: ReactNode; title?: string }) {
  const t = useLocalize();
  if (!scene || scene === 'select') return null;
  return <header className={`assistant-chat-heading${scene !== 'orders' ? ' assistant-chat-heading-stable' : ''}`}>
    <span title={title}>{t(`zhgyl.scenes.${scene}.label`)}</span>{actions}
    <Link to={scene === 'orders' ? '/c/new?module=order-tracking' : '/c/new'}>{t(scene === 'orders' ? 'zhgyl.backOrders' : 'zhgyl.switch')}</Link>
  </header>;
}
