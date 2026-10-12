import { createPreviewDiagnosticRecorder } from './previewDiagnostics';

describe('preview diagnostics', () => {
  it('does not collect anything while disabled', () => {
    const recorder = createPreviewDiagnosticRecorder();
    recorder.record('click', { visible: true });
    expect(recorder.snapshot()).toEqual([]);
  });

  it('retains only recent events and clears them when stopped', () => {
    const recorder = createPreviewDiagnosticRecorder(2);
    recorder.start();
    recorder.record('click', { visible: true });
    recorder.record('state', { open: true });
    recorder.record('mounted', { open: true });
    expect(recorder.snapshot().map(entry => entry.event)).toEqual(['state', 'mounted']);
    recorder.stop();
    recorder.record('click', {});
    expect(recorder.snapshot()).toEqual([]);
  });

  it('does not let exported snapshots modify the live recording', () => {
    const recorder = createPreviewDiagnosticRecorder();
    recorder.start();
    recorder.record('state', { open: true });
    recorder.snapshot()[0].data.open = false;
    expect(recorder.snapshot()[0].data.open).toBe(true);
  });

  it('pauses collection outside the knowledge page without losing earlier evidence', () => {
    const recorder = createPreviewDiagnosticRecorder();
    recorder.start();
    recorder.record('click', {});
    recorder.pause();
    recorder.record('request', {});
    expect(recorder.snapshot().map(entry => entry.event)).toEqual(['click']);
    recorder.start();
    recorder.record('state', {});
    expect(recorder.snapshot().map(entry => entry.event)).toEqual(['click', 'state']);
  });
});
