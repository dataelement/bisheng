import { useEffect, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useSearchParams } from 'react-router-dom';
import { Button } from '~/components/ui/Button';
import { useLocalize } from '~/hooks';
import {
  describePreviewDiagnosticElement,
  previewDiagnosticRecorder as recorder,
  recordPreviewDiagnosticSnapshot,
} from './previewDiagnostics';
import {
  getPreviewDiagnosticEnabled,
  getPreviewDiagnosticRemaining,
  setPreviewDiagnosticEnabled,
  subscribePreviewDiagnosticPreference,
} from './previewDiagnosticPreference';

interface PreviewDiagnosticsProps {
  open: boolean;
  fileId: string | null;
  spaceId: string;
}

export function PreviewDiagnostics({ open, fileId, spaceId }: PreviewDiagnosticsProps) {
  const localize = useLocalize();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const enabled = useSyncExternalStore(
    subscribePreviewDiagnosticPreference, getPreviewDiagnosticEnabled, () => false,
  );
  const [report, setReport] = useState('');

  useEffect(() => {
    if (!enabled) {
      setReport('');
      return;
    }
    recorder.start();
    recorder.record('diagnostics.started', { ua: navigator.userAgent });
    recordPreviewDiagnosticSnapshot('environment.initial');
    const handlePointer = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('[data-preview-diagnostics]')) return;
      const hit = document.elementFromPoint?.(event.clientX, event.clientY) ?? null;
      recorder.record(`capture.${event.type}`, {
        target: describePreviewDiagnosticElement(target),
        hit: describePreviewDiagnosticElement(hit),
        fileItem: Boolean(target?.closest('[data-knowledge-file-item]')),
        trusted: event.isTrusted,
        x: event.clientX,
        y: event.clientY,
      });
      recordPreviewDiagnosticSnapshot('environment.click');
    };
    const handleVisibility = () => recordPreviewDiagnosticSnapshot('visibility.changed');
    const handleFocus = () => recordPreviewDiagnosticSnapshot('window.focus');
    const handlePageShow = (event: PageTransitionEvent) => {
      recorder.record('page.show', { persisted: event.persisted });
      recordPreviewDiagnosticSnapshot('environment.pageshow');
    };
    const handleError = (event: ErrorEvent) => {
      // Error messages can contain document content or signed URLs: keep only the type.
      recorder.record('runtime.error', { name: event.error instanceof Error ? event.error.name : 'unknown' });
    };
    const handleRejection = (event: PromiseRejectionEvent) => {
      recorder.record('runtime.rejection', { name: event.reason instanceof Error ? event.reason.name : 'unknown' });
    };
    document.addEventListener('pointerdown', handlePointer, true);
    document.addEventListener('click', handlePointer, true);
    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('focus', handleFocus);
    window.addEventListener('pageshow', handlePageShow);
    window.addEventListener('error', handleError);
    window.addEventListener('unhandledrejection', handleRejection);
    const expiryTimer = window.setTimeout(() => {
      setPreviewDiagnosticEnabled(false);
    }, getPreviewDiagnosticRemaining());
    return () => {
      window.clearTimeout(expiryTimer);
      recorder.pause();
      document.removeEventListener('pointerdown', handlePointer, true);
      document.removeEventListener('click', handlePointer, true);
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('pageshow', handlePageShow);
      window.removeEventListener('error', handleError);
      window.removeEventListener('unhandledrejection', handleRejection);
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    recorder.record('preview.state', { open, fileId, spaceId });
    recorder.record('route.state', {
      previewFile: searchParams.get('preview'),
      previewChange: searchParams.get('previewChange'),
    });
    const timers = [300, 1500].map(delay => window.setTimeout(
      () => recordPreviewDiagnosticSnapshot(`drawer.dom.${delay}ms`), delay,
    ));
    return () => timers.forEach(timer => window.clearTimeout(timer));
  }, [enabled, open, fileId, spaceId, location.key, searchParams]);

  const handleExport = () => {
    recordPreviewDiagnosticSnapshot('export.snapshot');
    const content = JSON.stringify({ version: 1, events: recorder.snapshot() }, null, 2);
    setReport(content);
    const url = URL.createObjectURL(new Blob([content], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `preview-diagnostics-${Date.now()}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const handleStop = () => {
    setPreviewDiagnosticEnabled(false);
    setReport('');
  };

  if (!enabled) return null;
  return createPortal(
    <section data-preview-diagnostics
      onClick={event => event.stopPropagation()}
      onPointerDown={event => event.stopPropagation()}
      className="pointer-events-auto fixed right-4 top-4 z-[1000] max-w-[min(480px,90vw)] rounded-md border border-border-base bg-bg-1 p-3 text-body-sm text-text-1 shadow-md">
      <p>{localize('preview_diagnostics.active')}</p>
      <div className="mt-2 flex gap-2">
        <Button size="small" onClick={handleExport}>{localize('preview_diagnostics.export')}</Button>
        <Button size="small" color="default" variant="outlined" onClick={handleStop}>{localize('preview_diagnostics.stop')}</Button>
      </div>
      {report && (
        <label className="mt-2 block">
          {localize('preview_diagnostics.copy_hint')}
          <textarea readOnly value={report} onFocus={event => event.currentTarget.select()} className="mt-1 h-40 w-full border border-border-base bg-bg-1 text-body-sm text-text-1" />
        </label>
      )}
    </section>, document.body,
  );
}
