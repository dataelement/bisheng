import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

it('uses one verified local official SheetJS artifact for the entire workspace', () => {
  const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  expect(manifest.pnpm.overrides.xlsx).toBe('file:vendor/xlsx-0.20.3.tgz');
  const catalog = readFileSync(new URL('../pnpm-workspace.yaml', import.meta.url), 'utf8');
  expect(catalog).toMatch(/xlsx: 0\.20\.3/);
  const artifact = readFileSync(new URL('../vendor/xlsx-0.20.3.tgz', import.meta.url));
  const integrity = 'sha512-' + createHash('sha512').update(artifact).digest('base64');
  expect(integrity).toBe('sha512-oLDq3jw7AcLqKWH2AhCpVTZl8mf6X2YReP+Neh0SJUzV/BdZYjth94tG5toiMB1PPrYtxOCfaoUCkvtuH+3AJA==');
  const lockfile = readFileSync(new URL('../pnpm-lock.yaml', import.meta.url), 'utf8');
  expect(lockfile).toContain(`resolution: {integrity: ${integrity}, tarball: file:vendor/xlsx-0.20.3.tgz}`);
  expect(lockfile).not.toContain('https://cdn.sheetjs.com/');
});

// Resolve from each consumer so stale app-local dependencies cannot hide behind a root import.
for (const consumer of ['client', 'platform', 'packages/file-viewers']) {
  const require = createRequire(new URL(`../${consumer}/package.json`, import.meta.url));
  const xlsx = require('xlsx');

  describe(`SheetJS security and workbook compatibility: ${consumer}`, () => {
    it('uses the pinned release containing both security fixes', () => {
      expect(xlsx.version).toBe('0.20.3');
    });

    it.each(['xlsx', 'biff8'])('preserves preview and QA-import cells through %s export', (bookType) => {
      const rows = [['Question', 'Answer'], ['Line 1\nLine 2', 'Answer, with commas'], ['Unicode \u6d4b\u8bd5', '00123']];
      const workbook = xlsx.utils.book_new();
      xlsx.utils.book_append_sheet(workbook, xlsx.utils.aoa_to_sheet(rows), 'Sheet1');
      const bytes = xlsx.write(workbook, { bookType, type: 'array' });
      const parsed = xlsx.read(bytes, { type: 'array' });
      expect(xlsx.utils.sheet_to_json(parsed.Sheets.Sheet1, { header: 1, defval: '' })).toEqual(rows);
    });

    it('retains quoted CSV fields used by export', () => {
      const sheet = xlsx.utils.aoa_to_sheet([['Question', 'Answer'], ['Line 1\nLine 2', 'Answer, with commas']]);
      expect(xlsx.utils.sheet_to_csv(sheet)).toBe('Question,Answer\n"Line 1\nLine 2","Answer, with commas"');
    });
  });
}
