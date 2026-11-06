import { asRecord } from '../core/normalizeHistory';
export interface MermaidRuntime { initialize: (options: Record<string, unknown>) => void; run: (options: { nodes: HTMLElement[] }) => void | Promise<void> }
export interface ChartInstance { setOption: (option: unknown) => void; dispose: () => void; resize: () => void }
export interface EchartsRuntime { init: (node: HTMLElement) => ChartInstance }
export function readMermaidRuntime(value: unknown): MermaidRuntime {
  const raw = asRecord(value);
  if (typeof raw.initialize !== 'function' || typeof raw.run !== 'function') throw new Error('Mermaid runtime is unavailable');
  return value as MermaidRuntime;
}
export function readEchartsRuntime(value: unknown): EchartsRuntime {
  if (typeof asRecord(value).init !== 'function') throw new Error('Echarts runtime is unavailable');
  return value as EchartsRuntime;
}
export function normalizeMindmapIndent(code: string): string {
  const lines = code.split('\n'); const index = lines.findIndex(line => line.trim() === 'mindmap');
  if (index < 0) return code;
  const body = lines.slice(index + 1).filter(line => line.trim().length > 0);
  if (body.length && !/^[\t ]/.test(body[0])) return [...lines.slice(0, index + 1), ...body.map(line => `  ${line}`)].join('\n');
  return [...lines.slice(0, index + 1), ...body].join('\n');
}
/** Same local PNG export as client diagrams, scoped to the selected diagram. */
export async function downloadDiagram(node: HTMLElement, title = 'diagram'): Promise<void> {
  const svg = node.querySelector('svg'); if (!svg) return;
  const cloned = svg.cloneNode(true) as SVGElement;
  const box = svg.getBBox(); const width = box.width || svg.clientWidth; const height = box.height || svg.clientHeight;
  cloned.setAttribute('width', String(width)); cloned.setAttribute('height', String(height));
  const canvas = document.createElement('canvas'); canvas.width = width * 2; canvas.height = height * 2;
  const context = canvas.getContext('2d'); if (!context) return;
  context.scale(2, 2); context.fillStyle = 'white'; context.fillRect(0, 0, width, height);
  const picture = new Image();
  await new Promise<void>((resolve, reject) => {
    picture.onload = () => { context.drawImage(picture, 0, 0); resolve(); };
    picture.onerror = () => reject(new Error('Diagram image could not be loaded'));
    picture.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(cloned))}`;
  });
  const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve)); if (!blob) return;
  const link = document.createElement('a'); link.download = `${title}_${Date.now()}.png`; link.href = URL.createObjectURL(blob);
  link.click(); URL.revokeObjectURL(link.href);
}
