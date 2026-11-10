import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, it } from 'vitest';
import { diagramAssetTargets } from './diagramAssets';
it('copies exactly the two byte-preserved shared scripts from absolute source paths', () => {
  const targets = diagramAssetTargets();
  expect(targets.map(target => path.basename(target.src)).sort()).toEqual(['echarts.min.js', 'mermaid.min.js']);
  const manifestPath = path.resolve(import.meta.dirname, '../packages/diagram-runtime/assets/manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as Record<string, { sha256: string }>;
  for (const target of targets) {
    expect(path.isAbsolute(target.src)).toBe(true);
    expect(target.dest).toBe('.');
    expect(createHash('sha256').update(readFileSync(target.src)).digest('hex')).toBe(manifest[path.basename(target.src)].sha256);
  }
});
it('has no app-owned public source copies to drift apart', () => {
  for (const app of ['platform','client']) for (const name of ['echarts.min.js','mermaid.min.js']) {
    expect(existsSync(path.resolve(import.meta.dirname, '..', app, 'public', name))).toBe(false);
  }
});
