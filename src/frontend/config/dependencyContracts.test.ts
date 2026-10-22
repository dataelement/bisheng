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
    }
  });
  it('uses Axios own types instead of the deprecated stub', () => {
    expect(manifest('platform').devDependencies).not.toHaveProperty('@types/axios');
  });

  it('does not ship the unreachable legacy virtualized input library', () => {
    expect(manifest('client').dependencies).not.toHaveProperty('react-virtualized');
  });

  it('keeps both live file preview lists on the same catalog version', () => {
    for (const app of ['client', 'platform']) {
      expect(manifest(app).dependencies?.['react-window']).toBe('catalog:');
    }
  });

  it('retains the distinct active drag and color picker implementations', () => {
    expect(manifest('client').dependencies?.['react-dnd']).toBe('^16.0.1');
    expect(manifest('client').dependencies?.['react-dnd-html5-backend']).toBe('^16.0.1');
    expect(manifest('platform').dependencies?.['react-color']).toBe('^2.19.3');
  });
});
