import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, EmptyStateIllustration, StateView } from '@bisheng/ui';
import { MODULE_HOME_INTRO } from '~/components/ModuleHome';
import { useAuthContext, useLocalize, usePrefersMobileLayout } from '~/hooks';
import { getCloudWorkbenches, type CloudWorkbench } from '~/api/cloudWorkbenches';
import { cn } from '~/utils';
import { AgentCard } from './components/AgentCard';

/** These are the same hosted applications as Desktop workbenches, under the current web identity. */
export function CloudWorkbenches() {
  const localize = useLocalize();
  const { user } = useAuthContext();
  const isMobileLayout = usePrefersMobileLayout();
  const [items, setItems] = useState<CloudWorkbench[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async (after: string | null = null) => {
    controller.current?.abort();
    const attempt = new AbortController();
    controller.current = attempt;
    setLoading(true);
    setFailed(false);
    try {
      const page = await getCloudWorkbenches(after, attempt.signal);
      if (attempt.signal.aborted) return;
      setItems(previous => after ? [...previous, ...page.items.filter(item => !previous.some(row => row.id === item.id))] : page.items);
      setCursor(page.next_cursor);
    } catch {
      if (!attempt.signal.aborted) setFailed(true);
    } finally {
      if (!attempt.signal.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    setItems([]);
    setCursor(null);
    void load();
    return () => controller.current?.abort();
  }, [load, user]);

  const open = (item: CloudWorkbench) => {
    const url = new URL(item.entry_url, window.location.origin);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return;
    // The platform proxy rechecks the current visitor's visibility permission at entry.
    window.location.assign(url.href);
  };
  return <div className="flex h-full min-h-0 flex-col">
    <div className="my-4 flex shrink-0 items-center justify-between gap-3 max-md:flex-col max-md:items-start">
      <p className={cn('min-w-0 text-text-2', isMobileLayout ? 'text-body-sm' : [MODULE_HOME_INTRO, 'text-body'])}>
        {localize('shared:cloudWorkbenches.description')}
      </p>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Button variant="outlined" onClick={() => { void load(); }} loading={loading}>{localize('shared:cloudWorkbenches.refresh')}</Button>
        <Button asChild variant="link"><a href={`${__APP_ENV__.BASE_URL.replace(/\/$/, '')}/api/v1/dev-toolkit/workbench-guide.md`} target="_blank" rel="noopener noreferrer">{localize('shared:cloudWorkbenches.guide')}</a></Button>
      </div>
    </div>
    <main className="min-h-0 flex-1 overflow-auto" aria-busy={loading}>
      {failed && <p role="alert" className="mb-4 text-body-sm text-danger">{localize('shared:cloudWorkbenches.failed')}</p>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map(item => <AgentCard key={item.id} agent={{ id: item.id, name: item.name, description: item.description || '', logo: '', user_id: '', flow_type: 35, can_share: false }}
          openLabel={localize('shared:cloudWorkbenches.open')} onStartChat={() => open(item)} onShare={() => {}} />)}
      </div>
      {!loading && !failed && !cursor && items.length === 0 && (
        <StateView
          size="page"
          image={<EmptyStateIllustration />}
          title={<span role="status">{localize('shared:cloudWorkbenches.empty')}</span>}
          description={localize('shared:cloudWorkbenches.emptyDescription')}
        />
      )}
      {cursor && <Button variant="text" loading={loading} onClick={() => { void load(cursor); }}>{localize('shared:cloudWorkbenches.more')}</Button>}
    </main>
  </div>;
}
