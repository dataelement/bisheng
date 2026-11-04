import { ExcelPreview } from '@bisheng/file-viewers';
import { render,screen } from '@testing-library/react';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { afterEach,beforeAll,describe,expect,it,vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import sharedZh from '../../../../public/locales/zh-Hans/shared.json';

vi.unmock('react-i18next');

const i18n = createInstance();

beforeAll(async () => {
  await i18n.init({
    lng: 'zh-Hans',
    ns: ['shared'],
    defaultNS: 'shared',
    resources: { 'zh-Hans': { shared: sharedZh } },
    interpolation: { escapeValue: false },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Excel preview translations', () => {
  it.each(['xlsx', 'xls', 'et'])('renders real %s workbooks with the upgraded parser', async (extension) => {
    const fixtureExtension = extension === 'xls' ? 'xls' : 'xlsx';
    const fixture = readFileSync(resolve('../config/fixtures', `spreadsheet.${fixtureExtension}`));
    const data = Uint8Array.from(fixture).buffer;
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, arrayBuffer: async () => data })));
    render(
      <I18nextProvider i18n={i18n}>
        <ExcelPreview filePath={`/sample.${extension}`} fileExt={extension} />
      </I18nextProvider>,
    );
    expect(await screen.findByText('Sample question')).toBeInTheDocument();
    expect(screen.getByText('Sample answer')).toBeInTheDocument();
    expect(screen.getByText('00123')).toBeInTheDocument();
  });

  it('renders the translated row header from the host app i18n instance', async () => {
    const csv = new TextEncoder().encode('A\n33333').buffer;
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, arrayBuffer: async () => csv })));

    render(
      <I18nextProvider i18n={i18n}>
        <ExcelPreview filePath="/sample.csv" fileExt="csv" />
      </I18nextProvider>,
    );

    expect(await screen.findByRole('columnheader', { name: sharedZh.knowledge.excelPreview.rowNumber })).toBeInTheDocument();
  });
});
