export type DiagramKind = 'echarts' | 'mermaid';
export interface DiagramLoadOptions { baseUrl: string; timeoutMs?: number }
const pending = new WeakMap<Document, Map<DiagramKind, Promise<unknown>>>();

function runtime(kind: DiagramKind): unknown {
  return (window as unknown as Record<DiagramKind, unknown>)[kind];
}

/** Load the byte-preserved vendor global once per document; failures remain retryable. */
export function loadDiagramLibrary(kind: DiagramKind, options: DiagramLoadOptions): Promise<unknown> {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    return Promise.reject(new Error('Diagram loading requires a browser'));
  }
  if (kind !== 'echarts' && kind !== 'mermaid') return Promise.reject(new Error('Unsupported diagram library'));
  const ready = runtime(kind);
  if (ready) return Promise.resolve(ready);
  let requests = pending.get(document);
  if (!requests) { requests = new Map(); pending.set(document, requests); }
  const active = requests.get(kind);
  if (active) return active;

  const script = document.createElement('script');
  script.src = `${options.baseUrl.replace(/\/+$/, '')}/${kind}.min.js`;
  script.type = 'module';
  let resolve!: (library: unknown) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<unknown>((accept, fail) => { resolve = accept; reject = fail; });
  requests.set(kind, promise);
  let settled = false;
  let poll: number | undefined;
  const finish = (error?: Error, library?: unknown) => {
    if (settled) return;
    settled = true;
    window.clearTimeout(timer);
    window.clearInterval(poll);
    script.onload = null;
    script.onerror = null;
    if (requests.get(kind) === promise) requests.delete(kind);
    if (error) { script.remove(); reject(error); } else resolve(library);
  };
  const checkReady = () => {
    if (settled) return;
    const library = runtime(kind);
    if (library) finish(undefined, library);
  };
  script.onload = () => {
    if (settled) return;
    checkReady();
    if (!settled && poll === undefined) poll = window.setInterval(checkReady, 25);
  };
  script.onerror = () => finish(new Error(`Failed to load ${kind}`));
  const timer = window.setTimeout(() => finish(new Error(`Timed out loading ${kind}`)), options.timeoutMs ?? 15_000);
  try { document.head.appendChild(script); } catch { finish(new Error(`Failed to load ${kind}`)); }
  return promise;
}
