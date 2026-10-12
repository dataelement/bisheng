type DiagnosticValue = string | number | boolean | null;
type DiagnosticEntry = { time: string; event: string; data: Record<string, DiagnosticValue> };

export function createPreviewDiagnosticRecorder(limit = 300) {
  let enabled = false;
  let entries: DiagnosticEntry[] = [];
  return {
    start() { enabled = true; },
    pause() { enabled = false; },
    stop() { enabled = false; entries = []; },
    record(event: string, data: Record<string, DiagnosticValue>) {
      if (!enabled) return;
      entries.push({ time: new Date().toISOString(), event, data: { ...data } });
      entries = entries.slice(-limit);
    },
    snapshot() { return entries.map(entry => ({ ...entry, data: { ...entry.data } })); },
  };
}

export const previewDiagnosticRecorder = createPreviewDiagnosticRecorder();

/** Only structural DOM metadata: never text, document names, URLs or credentials. */
export function describePreviewDiagnosticElement(element: Element | null): string {
  if (!element) return 'none';
  const style = getComputedStyle(element);
  const rect = element.getBoundingClientRect();
  return JSON.stringify({
    tag: element.tagName,
    slot: element.getAttribute('data-slot'),
    role: element.getAttribute('role'),
    state: element.getAttribute('data-state'),
    fileItem: element.hasAttribute('data-knowledge-file-item'),
    previewDrawer: element.hasAttribute('data-preview-file-drawer'),
    pointerEvents: style.pointerEvents,
    visibility: style.visibility,
    display: style.display,
    opacity: style.opacity,
    zIndex: style.zIndex,
    rect: [rect.x, rect.y, rect.width, rect.height].map(Math.round),
  });
}

export function recordPreviewDiagnosticSnapshot(event: string) {
  previewDiagnosticRecorder.record(event, {
    visible: document.visibilityState,
    focused: document.hasFocus(),
    online: navigator.onLine,
    width: window.innerWidth,
    bodyPointerEvents: getComputedStyle(document.body).pointerEvents,
    layers: JSON.stringify(Array.from(document.querySelectorAll(
      '[data-slot="sheet-overlay"], [data-slot="sheet-content"], [role="dialog"], [data-radix-popper-content-wrapper]',
    )).slice(0, 15).map(describePreviewDiagnosticElement)),
  });
}
