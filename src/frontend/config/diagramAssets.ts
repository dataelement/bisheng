import { fileURLToPath } from 'node:url';
import { normalizePath } from 'vite';

/** Shared source, independent app outputs; static-copy also serves these in development. */
export function diagramAssetTargets(): Array<{ src: string; dest: string }> {
  return ['echarts.min.js', 'mermaid.min.js'].map(name => ({
    src: normalizePath(fileURLToPath(new URL(`../packages/diagram-runtime/assets/${name}`, import.meta.url))),
    dest: '.',
  }));
}
