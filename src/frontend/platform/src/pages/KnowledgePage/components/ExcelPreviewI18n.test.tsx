import { render, screen } from '@testing-library/react';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { ExcelPreview } from '@bisheng/file-viewers';
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
