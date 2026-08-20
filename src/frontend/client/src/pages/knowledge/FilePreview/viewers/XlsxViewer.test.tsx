import { render, waitFor } from '@testing-library/react';
import { ExcelPreview } from '@bisheng/file-viewers';

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    // Deliberately return a new function on every render. Translation identity
    // changes must not restart the file request and parsing lifecycle.
    t: (key: string) => key,
  }),
}));

jest.mock('xlsx', () => ({
  read: jest.fn(() => ({
    SheetNames: ['Sheet1'],
    Sheets: { Sheet1: {} },
  })),
  utils: {
    sheet_to_json: jest.fn(() => [['Name'], ['BISHENG']]),
  },
}));

jest.mock('xlsx-populate', () => ({
  __esModule: true,
  default: {
    fromDataAsync: jest.fn(() => Promise.reject(new Error('No embedded images'))),
  },
}));

describe('ExcelPreview', () => {
  it('loads the same file only once when the translation function identity changes', async () => {
    const fetchMock = jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(8),
    } as Response);

    const { rerender } = render(<ExcelPreview filePath="/files/report.xlsx" fileExt="xlsx" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(document.body.textContent).toContain('BISHENG'));

    rerender(<ExcelPreview filePath="/files/report.xlsx" fileExt="xlsx" />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });
});
