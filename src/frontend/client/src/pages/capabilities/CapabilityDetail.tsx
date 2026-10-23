import { useState } from 'react';
import { Button, Input, Switch } from '@bisheng/ui';
import { CheckCircle2, Play } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';
import { runCapabilityTrial, type Capability, type CapabilityResult } from '~/api/capabilities';

interface CapabilityDetailProps {
  item: Capability;
  onClose: () => void;
  availability?: { checked: boolean; busy: boolean; onChange: (enabled: boolean) => void };
  availabilityError?: string;
}
export function CapabilityDetail({ item, onClose, availability, availabilityError }: CapabilityDetailProps) {
  const localize = useLocalize();
  const t = (key: string) => localize(`com_capability_center.${key}`);
  const [args, setArgs] = useState(item.trial?.arguments ?? {});
  const [result, setResult] = useState<CapabilityResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const title = item.trial ? t(`scenario_${item.trial.scenario}`) : item.name;
  const handleRun = async () => {
    if (busy || availability?.checked === false) return;
    setBusy(true); setError(''); setResult(null);
    try { setResult(await runCapabilityTrial(item.resource_id, args)); }
    catch { setError(t('trial_failed')); }
    finally { setBusy(false); }
  };
  return <Dialog open onOpenChange={next => { if (!next && !busy) onClose(); }}>
    <DialogContent close={false} className="flex max-h-[85dvh] w-[calc(100%-40px)] max-w-[720px] flex-col gap-0 overflow-hidden rounded-2xl border-border-base bg-bg-page p-0">
      <header className="flex items-center justify-between gap-4 border-b border-border-base px-6 py-4">
        <div className="min-w-0"><DialogTitle className="text-h4 text-text-1">{title}</DialogTitle>
          <DialogDescription className="mt-1 text-caption text-text-3">{t(item.kind === 'skill' ? 'skill' : 'tool')} · {item.provider}</DialogDescription></div>
        <Button color="default" variant="text" size="small" disabled={busy} onClick={onClose}>{t('close')}</Button>
      </header>
      <div className="scrollbar-os space-y-6 overflow-y-auto p-6">
        <p className="whitespace-pre-wrap text-body-sm leading-relaxed text-text-2">{item.description}</p>
        {item.trial ? <section className="space-y-4 rounded-lg border border-border-base bg-fill-1 p-4">
          <div><h3 className="text-body font-medium text-text-1">{t('try_title')}</h3><p className="mt-1 text-caption text-text-3">{t(item.demo ? 'demo_explanation' : 'live_explanation')}</p></div>
          {Object.entries(args).map(([name, value]) => <label key={name} className="block space-y-2">
            <span className="text-body-sm text-text-2">{t(`field_${name}`)}</span>
            <Input value={value} onChange={event => setArgs(current => ({ ...current, [name]: event.target.value }))} disabled={busy} />
          </label>)}
          <Button size="medium" loading={busy} disabled={availability?.checked === false || availability?.busy} onClick={handleRun} icon={<Play className="size-4" />}>{t('run')}</Button>
        </section> : null}
        {availability && <div className="flex items-center justify-between gap-4">
          <label htmlFor="capability-availability" className="text-body-sm text-text-1">{t('tool_enabled_setting')}</label>
          <Switch id="capability-availability" checked={availability.checked} loading={availability.busy} disabled={availability.busy} onCheckedChange={availability.onChange} aria-label={t('tool_enabled_setting')} />
        </div>}
        {availabilityError && <p role="alert" className="text-body-sm text-danger">{availabilityError}</p>}
        {error && <p role="alert" className="text-body-sm text-danger">{error}</p>}
        {result && <section aria-live="polite" className="space-y-3">
          <div className="flex items-center gap-2 text-body-sm text-success"><CheckCircle2 className="size-4" />{t('success')}<span className="ml-auto text-caption text-text-3">{result.elapsed_ms} ms</span></div>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border-base bg-fill-1 p-4 font-mono text-caption leading-relaxed text-text-1">{JSON.stringify(result.result, null, 2)}</pre>
          <p className="text-caption text-text-3">{t('audit_hint')}</p>
        </section>}
      </div>
    </DialogContent>
  </Dialog>;
}
