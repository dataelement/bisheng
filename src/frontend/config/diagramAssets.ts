import { fileURLToPath } from 'node:url';

/** Shared source, independent app outputs; static-copy also serves these in development. */
export function diagramAssetTargets(): Array<{ src: string; dest: string }> {
  return ['echarts.min.js', 'mermaid.min.js'].map(name => ({
    src: fileURLToPath(new URL(`../packages/diagram-runtime/assets/${name}`, import.meta.url)),
    dest: '.',
  }));
}
