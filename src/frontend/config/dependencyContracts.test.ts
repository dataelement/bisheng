import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

interface Manifest {
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
}

function manifest(app: string): Manifest {
  return JSON.parse(readFileSync(new URL(`../${app}/package.json`, import.meta.url), 'utf8'));
}

describe('frontend dependency ownership', () => {
  it('uses the maintained list sorting library in both applications', () => {
    for (const app of ['client', 'platform']) {
      expect(manifest(app).dependencies?.['@hello-pangea/dnd']).toBe('catalog:');
      expect(manifest(app).dependencies).not.toHaveProperty('react-beautiful-dnd');
    }
  });
  it('uses Axios own types instead of the deprecated stub', () => {
    expect(manifest('platform').devDependencies).not.toHaveProperty('@types/axios');
  });

  it('does not ship the unreachable legacy virtualized input library', () => {
    expect(manifest('client').dependencies).not.toHaveProperty('react-virtualized');
  });

  it('keeps PDF virtualization only in the platform host that uses it', () => {
    expect(manifest('platform').dependencies?.['react-window']).toBe('catalog:');
    expect(manifest('client').dependencies).not.toHaveProperty('react-window');
  });
  it('owns DOCX parsing in the shared preview package', () => {
    expect(manifest('packages/file-viewers').dependencies?.mammoth).toBe('1.12.0');
    for (const app of ['client', 'platform']) expect(manifest(app).dependencies).not.toHaveProperty('mammoth');
  });

  it('retains the distinct active drag and color picker implementations', () => {
    expect(manifest('client').dependencies?.['react-dnd']).toBe('^16.0.1');
    expect(manifest('client').dependencies?.['react-dnd-html5-backend']).toBe('^16.0.1');
    expect(manifest('platform').dependencies?.['react-color']).toBe('^2.19.3');
  });
});
