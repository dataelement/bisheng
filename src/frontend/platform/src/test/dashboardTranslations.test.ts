import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

const frontend = path.resolve(__dirname, '../../..');
const definitions = readFileSync(path.resolve(frontend, '../backend/bisheng/telemetry_search/domain/init_dataset.py'), 'utf8');
// These are the keys the selector receives from the backend, rather than literal t() calls.
const datasets = [...definitions.matchAll(/dataset_code\s*=\s*["']([^"']+)/g)].map(match => match[1]);
const fields = [...definitions.matchAll(/(?:MetricConfig|DimensionConfig)\([\s\S]*?\bfield\s*=\s*["']([^"']+)/g)].map(match => match[1]);
const keys = [...new Set([...datasets, ...fields.filter(field => field !== 'timestamp'), ...['year', 'month', 'week', 'day', 'hour'].map(unit => `timestamp.${unit}`)])];

describe('dashboard dataset translations', () => {
  it.each(['zh-Hans', 'en-US', 'ja'])('translates live dataset and field keys in %s', async (language) => {
    const messages = JSON.parse(readFileSync(path.join(frontend, `platform/public/locales/${language}/dashboard.json`), 'utf8'));
    const instance = i18next.createInstance();
    await instance.init({ lng: language, fallbackLng: false, defaultNS: 'dashboard', resources: { [language]: { dashboard: messages } } });
    expect(datasets.length).toBeGreaterThan(0);
    for (const key of keys) {
      expect(instance.exists(key), `${language}: ${key}`).toBe(true);
      expect(instance.t(key)).not.toBe(key);
    }
  });

  it('protects backend-provided translation keys from dead-key deletion', () => {
    execFileSync(process.execPath, ['scripts/find-dead-i18n-keys.mjs'], { cwd: frontend });
    const report = JSON.parse(readFileSync(path.join(frontend, 'scripts/i18n-dead-keys-report.json'), 'utf8'));
    const deletable = new Set<string>(report.platform['dashboard.json'].safe);
    expect(keys.filter(key => deletable.has(key))).toEqual([]);
  }, 20000);
});
