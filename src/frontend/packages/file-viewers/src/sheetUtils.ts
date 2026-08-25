import type { CleanedSheet, SheetData } from './types';

const VALID_EXTENSIONS = ['csv', 'xlsx', 'xls', 'et', 'txt'];

export const MIME_TYPES: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  bmp: 'image/bmp',
  jfif: 'image/jpeg',
  tiff: 'image/tiff',
  tif: 'image/tiff',
  svg: 'image/svg+xml',
};

export function getFileExtension(filePath: string): string {
  if (!filePath) return '';
  const withoutQuery = filePath.split('?')[0];
  const parts = withoutQuery.split('.');
  if (parts.length < 2) return '';
  const ext = parts.pop()?.toLowerCase() || '';
  return VALID_EXTENSIONS.includes(ext) ? ext : '';
}

export function numberToColumnLetters(num: number): string {
  let result = '';
  while (num >= 0) {
    result = String.fromCharCode(65 + (num % 26)) + result;
    num = Math.floor(num / 26) - 1;
  }
  return result;
}

export function extractImageIdFromFormula(formula: unknown): string | null {
  if (!formula || typeof formula !== 'string') return null;
  const patterns = [
    /DISPIMG\("([^"]+)"\)/i,
    /DISPIMG\('([^']+)'\)/i,
    /DISPIMG\("([^"]+)",\s*\d+\)/i,
    /DISPIMG\('([^']+)',\s*\d+\)/i,
  ];
  for (const pattern of patterns) {
    const match = formula.match(pattern);
    if (match && match[1]) return match[1];
  }
  return null;
}

export function parseCSV(csvStr: string): SheetData {
  try {
    if (!csvStr || typeof csvStr !== 'string') return [];
    const lines = csvStr.split(/\r?\n/).filter((line) => line.trim() !== '');
    const rows: SheetData = [];
    const delimiters = [',', '\t', ';', '|'];

    let detectedDelimiter = ',';
    let maxColumns = 0;
    for (const delimiter of delimiters) {
      const testRow = lines[0]?.split(delimiter) || [];
      if (testRow.length > maxColumns && testRow.some((col) => col.trim() !== '')) {
        maxColumns = testRow.length;
        detectedDelimiter = delimiter;
      }
    }

    lines.forEach((line) => {
      const columns = line.split(detectedDelimiter).map((col) => col.replace(/^["']|["']$/g, '').trim());
      if (columns.some((col) => col !== '')) rows.push(columns);
    });
    return rows;
  } catch (err) {
    console.error('CSV parsing error:', err);
    return [];
  }
}

function hasValue(cell: unknown): boolean {
  return cell !== undefined && cell !== null && String(cell).trim() !== '';
}

/**
 * Drop fully blank rows and columns, and report which original row/column each
 * surviving index came from — drawing anchors address the original grid.
 */
export function cleanData(data: unknown[][]): CleanedSheet {
  const empty: CleanedSheet = { data: [], rowMap: [], colMap: [] };
  if (!Array.isArray(data) || data.length === 0) return empty;

  const rowMap: number[] = [];
  data.forEach((row, index) => {
    if (Array.isArray(row) && row.some(hasValue)) rowMap.push(index);
  });
  if (rowMap.length === 0) return empty;

  const columnCount = Math.max(...rowMap.map((index) => data[index].length));
  const colMap: number[] = [];
  for (let col = 0; col < columnCount; col++) {
    if (rowMap.some((index) => hasValue(data[index][col]))) colMap.push(col);
  }

  return {
    data: rowMap.map((index) => colMap.map((col) => (hasValue(data[index][col]) ? String(data[index][col]).trim() : ''))),
    rowMap,
    colMap,
  };
}

export function getTableColumnCount(data: SheetData): number {
  if (!Array.isArray(data) || data.length === 0) return 0;
  return Math.max(...data.map((row) => row.length));
}
