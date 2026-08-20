import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import * as XLSX from 'xlsx';
import XlsxPopulate, { type Workbook } from 'xlsx-populate/browser/xlsx-populate';

export interface ExcelPreviewProps {
  filePath: string;
  /** Prefer passing the extension from the parent; falls back to URL parsing. */
  fileExt?: string;
  /** Brand loading indicator; defaults to a neutral spinner. */
  loadingIcon?: ReactNode;
}

interface ExtractedImage {
  id: string;
  path: string;
  ext: string;
  base64: string;
  mimeType: string;
}

type SheetData = string[][];

const VALID_EXTENSIONS = ['csv', 'xlsx', 'xls', 'et', 'txt'];

const MIME_TYPES: Record<string, string> = {
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

function getFileExtension(filePath: string): string {
  if (!filePath) return '';
  const withoutQuery = filePath.split('?')[0];
  const parts = withoutQuery.split('.');
  if (parts.length < 2) return '';
  const ext = parts.pop()?.toLowerCase() || '';
  return VALID_EXTENSIONS.includes(ext) ? ext : '';
}

function numberToColumnLetters(num: number): string {
  let result = '';
  while (num >= 0) {
    result = String.fromCharCode(65 + (num % 26)) + result;
    num = Math.floor(num / 26) - 1;
  }
  return result;
}

function extractImageIdFromFormula(formula: unknown): string | null {
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

function parseCSV(csvStr: string): SheetData {
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

function cleanData(data: unknown[][]): SheetData {
  if (!Array.isArray(data) || data.length === 0) return [];

  const nonEmptyRows = data.filter((row) =>
    row.some((cell) => cell !== undefined && cell !== null && String(cell).trim() !== ''),
  );
  if (nonEmptyRows.length === 0) return [];

  const columnCount = Math.max(...nonEmptyRows.map((row) => row.length));
  const hasDataColumns: number[] = [];
  for (let col = 0; col < columnCount; col++) {
    const hasData = nonEmptyRows.some(
      (row) => row[col] !== undefined && row[col] !== null && String(row[col]).trim() !== '',
    );
    if (hasData) hasDataColumns.push(col);
  }

  return nonEmptyRows.map((row) => hasDataColumns.map((colIndex) => (row[colIndex] ? String(row[colIndex]).trim() : '')));
}

function getTableColumnCount(data: SheetData): number {
  if (!Array.isArray(data) || data.length === 0) return 0;
  return Math.max(...data.map((row) => row.length));
}

async function extractImagesWithPositions(workbook: Workbook): Promise<{
  images: ExtractedImage[];
  imagePositions: Record<string, string[]>;
}> {
  interface PendingImage {
    id: string;
    path: string;
    ext: string;
    base64Promise: Promise<string>;
  }
  const pending: PendingImage[] = [];
  const imagePositions: Record<string, string[]> = {};
  const zip = workbook._zip;

  zip.forEach((relativePath, zipEntry) => {
    if (relativePath.startsWith('xl/media/') && !zipEntry.dir) {
      const ext = relativePath.split('.').pop()?.toLowerCase() || '';
      if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif', 'jfif'].includes(ext)) {
        const id = relativePath.split('/').pop() || relativePath;
        pending.push({ id, path: relativePath, ext, base64Promise: zipEntry.async('base64') });
      }
    }
  });

  const drawingFiles = Object.keys(zip.files).filter((p) => p.startsWith('xl/drawings/') && p.endsWith('.xml'));
  for (const drawingPath of drawingFiles) {
    try {
      const xmlStr = await zip.file(drawingPath)?.async('text');
      if (!xmlStr) continue;
      const parser = new DOMParser();
      const xmlDoc = parser.parseFromString(xmlStr, 'text/xml');
      const anchors = xmlDoc.getElementsByTagName('xdr:twoCellAnchor');

      const relsPath = drawingPath.replace('drawings/', 'drawings/_rels/') + '.rels';
      const rIdMap: Record<string, string> = {};
      const relsEntry = zip.file(relsPath);
      if (relsEntry) {
        const relsXml = await relsEntry.async('text');
        const relsDoc = parser.parseFromString(relsXml, 'text/xml');
        const relationships = relsDoc.getElementsByTagName('Relationship');
        for (let j = 0; j < relationships.length; j++) {
          const r = relationships[j];
          const id = r.getAttribute('Id');
          const target = r.getAttribute('Target');
          if (id && target) rIdMap[id] = target.split('/').pop() || target;
        }
      }

      for (let i = 0; i < anchors.length; i++) {
        const anchor = anchors[i];
        const from = anchor.getElementsByTagName('xdr:from')[0];
        const pic = anchor.getElementsByTagName('xdr:pic')[0];
        if (!from || !pic) continue;

        const colNode = from.getElementsByTagName('xdr:col')[0];
        const rowNode = from.getElementsByTagName('xdr:row')[0];
        const blip = pic.getElementsByTagName('a:blip')[0];
        if (!colNode || !rowNode || !blip) continue;

        const col = parseInt(colNode.textContent || '0', 10);
        const row = parseInt(rowNode.textContent || '0', 10);
        const cellAddress = numberToColumnLetters(col) + (row + 1);

        const rId = blip.getAttribute('r:embed');
        if (!rId || !rIdMap[rId]) continue;

        const mediaFileName = rIdMap[rId];
        if (pending.some((img) => img.id === mediaFileName)) {
          if (!imagePositions[cellAddress]) imagePositions[cellAddress] = [];
          imagePositions[cellAddress].push(mediaFileName);
        }
      }
    } catch (e) {
      console.warn('Failed to parse drawing xml:', e);
    }
  }

  const images: ExtractedImage[] = [];
  for (const img of pending) {
    images.push({
      id: img.id,
      path: img.path,
      ext: img.ext,
      base64: await img.base64Promise,
      mimeType: MIME_TYPES[img.ext] || 'image/png',
    });
  }

  return { images, imagePositions };
}

function DefaultSpinner() {
  return (
    <svg className="size-20 animate-spin text-blue-500" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export function ExcelPreview({ filePath, fileExt: fileExtProp, loadingIcon }: ExcelPreviewProps) {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.excelPreview' });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sheets, setSheets] = useState<string[]>([]);
  const [activeSheet, setActiveSheet] = useState('');
  const [excelData, setExcelData] = useState<Record<string, SheetData>>({});
  const [images, setImages] = useState<ExtractedImage[]>([]);
  const [imagePositions, setImagePositions] = useState<Record<string, string[]>>({});
  const tableContainerRef = useRef<HTMLDivElement>(null);

  const fileExt = fileExtProp || getFileExtension(filePath);
  const isCSV = fileExt === 'csv';
  const isXLSX = fileExt === 'xlsx' || fileExt === 'et';

  const getCellImage = useCallback(
    (rowIndex: number, colIndex: number, cellContent: string): ExtractedImage | null => {
      const cellAddress = `${numberToColumnLetters(colIndex)}${rowIndex + 1}`;
      const imageIds = imagePositions[cellAddress];

      if (imageIds?.length) {
        const foundImage = images.find((img) => imageIds.includes(img.id));
        if (foundImage) return foundImage;
      }

      if (cellContent && typeof cellContent === 'string' && cellContent.startsWith('=DISPIMG')) {
        const imageId = extractImageIdFromFormula(cellContent);
        if (imageId) {
          const imageById = images.find((img) => img.path.includes(imageId) || img.id === imageId);
          if (imageById) return imageById;
          if (images.length > 0) return images[0];
        }
      }

      return null;
    },
    [images, imagePositions],
  );

  useEffect(() => {
    const fetchAndParseFile = async () => {
      try {
        setLoading(true);
        setImages([]);
        setImagePositions({});
        setExcelData({});
        setSheets([]);
        setActiveSheet('');

        if (!filePath) throw new Error(t('filePathEmpty'));

        const response = await fetch(filePath);
        if (!response.ok) throw new Error(`${t('fileLoadFailed')}: ${response.status}`);

        const arrayBuffer = await response.arrayBuffer();

        if (isCSV) {
          if (arrayBuffer.byteLength === 0) throw new Error(t('fileContentEmpty'));

          const uint8Array = new Uint8Array(arrayBuffer);
          let decodedStr = '';

          const encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'shift_jis'];
          for (const encoding of encodings) {
            try {
              decodedStr = new TextDecoder(encoding, { fatal: true }).decode(uint8Array);
              if (decodedStr.charCodeAt(0) === 0xfeff) decodedStr = decodedStr.slice(1);
              break;
            } catch {
              continue;
            }
          }
          if (!decodedStr) decodedStr = new TextDecoder().decode(uint8Array);

          const cleanedData = cleanData(parseCSV(decodedStr));
          setExcelData({ Sheet1: cleanedData });
          setSheets(['Sheet1']);
          setActiveSheet('Sheet1');
        } else if (isXLSX || fileExt === 'xls') {
          // 1. Use SheetJS as primary parser (handles .xls binary, WPS files,
          //    and non-conformant .xlsx that xlsx-populate chokes on).
          let wb: XLSX.WorkBook;
          try {
            wb = XLSX.read(arrayBuffer, { type: 'array' });
          } catch (e) {
            console.error('SheetJS parsing failed:', e);
            throw new Error(t('excelParseFailed'));
          }

          const sheetNames = wb.SheetNames;
          const parsedData: Record<string, SheetData> = {};
          sheetNames.forEach((sheetName) => {
            const aoa = XLSX.utils.sheet_to_json(wb.Sheets[sheetName], {
              header: 1,
              defval: '',
            }) as unknown[][];
            parsedData[sheetName] = cleanData(aoa);
          });
          setExcelData(parsedData);
          setSheets(sheetNames);
          setActiveSheet(sheetNames[0] || '');

          // 2. Image extraction is best-effort; failure must not block table rendering.
          //    Only attempt for .xlsx/.et — xlsx-populate cannot read legacy .xls.
          if (isXLSX) {
            try {
              const workbook = await XlsxPopulate.fromDataAsync(arrayBuffer);
              const extracted = await extractImagesWithPositions(workbook);
              setImages(extracted.images);
              setImagePositions(extracted.imagePositions);
            } catch (e) {
              console.warn('[ExcelPreview] image extraction failed, skipping:', e);
            }
          }
        } else {
          throw new Error(t('unsupportedType', { type: fileExt }));
        }

        setError(null);
      } catch (err) {
        console.error('File parsing failed:', err);
        setError(err instanceof Error ? err.message : t('unknownError'));
      } finally {
        setLoading(false);
      }
    };

    if (filePath) {
      fetchAndParseFile();
    } else {
      setLoading(false);
      setError(t('filePathEmpty'));
    }
  }, [filePath, fileExt, isCSV, isXLSX, t]);

  const renderContent = () => {
    const sheetData = excelData[activeSheet];
    if (!Array.isArray(sheetData) || sheetData.length === 0) {
      return (
        <div className="flex flex-1 min-h-0 items-center justify-center text-gray-500">
          {t('currentSheetNoData')}
        </div>
      );
    }

    const displayData = [...sheetData];
    const columnCount = getTableColumnCount(displayData);

    const calculateColumnWidths = () => {
      const widths: number[] = [];
      if (displayData.length > 0 && columnCount > 0) {
        widths.push(60);
        for (let i = 0; i < columnCount; i++) {
          const maxLength = displayData.reduce((max, row) => {
            const cellLength = String(row[i] || '').length;
            return cellLength > max ? cellLength : max;
          }, 0);

          let width;
          if (maxLength < 10) width = 120;
          else if (maxLength < 20) width = 180;
          else if (maxLength < 30) width = 220;
          else if (maxLength < 50) width = 280;
          else width = 320;

          widths.push(width);
        }
      }
      return widths;
    };

    const columnWidths = calculateColumnWidths();

    return (
      <div className="flex flex-col relative flex-1 min-h-0">
        <div
          ref={tableContainerRef}
          className="flex-1 min-h-0 border border-gray-200 bg-white relative overflow-auto"
          style={{ width: '100%', overflowX: 'auto' }}
        >
          <div className="min-w-full">
            <table className="min-w-full border-collapse">
              <thead className="bg-gray-50">
                {/* Column letters row */}
                <tr>
                  <th
                    className="border border-gray-200 bg-gray-100 text-gray-600 text-xs font-medium"
                    style={{ minWidth: '60px', maxWidth: '60px', padding: '8px 4px', textAlign: 'center' }}
                  >
                    {/* Top-left empty cell */}
                  </th>
                  {Array.from({ length: columnCount }).map((_, index) => (
                    <th
                      key={`col-header-${index}`}
                      className="border border-gray-200 bg-gray-100 text-gray-600 text-xs font-medium text-center"
                      style={{ minWidth: `${columnWidths[index + 1] || 200}px`, maxWidth: '400px', padding: '8px 4px' }}
                    >
                      {numberToColumnLetters(index)}
                    </th>
                  ))}
                </tr>

                {/* Data header row */}
                <tr>
                  <th
                    className="border border-gray-200 bg-gray-50 text-gray-700 text-xs font-medium"
                    style={{
                      minWidth: '60px',
                      maxWidth: '60px',
                      padding: '12px 8px',
                      textAlign: 'center',
                      boxShadow: '2px 0 0 #e5e7eb',
                    }}
                  >
                    {t('rowNumber')}
                  </th>
                  {displayData[0]?.map((header, index) => (
                    <th
                      key={index}
                      className="text-left text-xs font-medium text-gray-700 uppercase tracking-wider border border-gray-200 bg-gray-50 whitespace-nowrap"
                      style={{
                        minWidth: `${columnWidths[index + 1] || 200}px`,
                        maxWidth: '400px',
                        padding: '12px 16px',
                        boxShadow: '0 1px 0 #e5e7eb',
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <span className="truncate font-semibold" title={String(header)}>
                          {String(header || t('defaultColumnName', { index: index + 1 }))}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody className="bg-white divide-y divide-gray-200">
                {displayData.slice(1).map((row, rowIndex) => {
                  const actualRowIndex = rowIndex + 1;

                  return (
                    <tr
                      key={rowIndex}
                      className={`hover:bg-blue-50 transition-colors duration-150 ${rowIndex % 2 === 0 ? 'bg-white' : 'bg-gray-50/30'}`}
                    >
                      <td
                        className="border border-gray-200 bg-gray-50 text-gray-600 text-xs font-medium text-center sticky left-0 z-5"
                        style={{ minWidth: '60px', maxWidth: '60px', padding: '10px 8px', boxShadow: '2px 0 0 #e5e7eb' }}
                      >
                        {actualRowIndex}
                      </td>

                      {row.map((cell, cellIndex) => {
                        const cellImage = getCellImage(actualRowIndex, cellIndex, cell);
                        const isImageCell = cellImage !== null;

                        return (
                          <td
                            key={cellIndex}
                            className="text-sm text-gray-800 border border-gray-200 align-top"
                            style={{
                              minWidth: `${columnWidths[cellIndex + 1] || 200}px`,
                              maxWidth: '400px',
                              padding: isImageCell ? '2px' : '10px 16px',
                              wordBreak: 'break-word',
                              position: 'relative',
                              backgroundColor: isImageCell ? '#f0f9ff' : 'transparent',
                              verticalAlign: isImageCell ? 'middle' : 'top',
                              height: isImageCell ? '120px' : 'auto',
                            }}
                          >
                            {isImageCell && cellImage ? (
                              <div className="flex items-center justify-center p-1 h-full" style={{ minHeight: '100px', width: '100%' }}>
                                <img
                                  src={`data:${cellImage.mimeType};base64,${cellImage.base64}`}
                                  alt={`${t('imageRef')} ${actualRowIndex}-${cellIndex + 1}`}
                                  className="max-w-full max-h-full object-contain"
                                  onError={(e) => {
                                    const target = e.target as HTMLImageElement;
                                    target.style.display = 'none';
                                    const parent = target.parentElement;
                                    if (!parent) return;
                                    const imageId = extractImageIdFromFormula(cell);
                                    parent.innerHTML = `
                                      <div class="flex flex-col items-center justify-center p-2 text-gray-500 text-xs h-full w-full">
                                        <svg class="w-6 h-6 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                        </svg>
                                        <span>${t('imageLoadFailed')}</span>
                                        ${imageId ? `<span class="text-xs mt-1 text-center">ID: ${imageId}</span>` : ''}
                                      </div>
                                    `;
                                  }}
                                />
                              </div>
                            ) : (
                              <div className="leading-relaxed" style={{ maxHeight: '150px', overflow: 'auto', lineHeight: '1.6' }}>
                                {cell && typeof cell === 'string' && cell.startsWith('=DISPIMG') ? (
                                  <div className="flex flex-col items-center justify-center p-2 text-blue-600 text-xs bg-blue-50 rounded border border-blue-200 min-h-[80px]">
                                    <svg className="w-5 h-5 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                      <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2}
                                        d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
                                      />
                                    </svg>
                                    <span className="text-center">{t('imageRef')}</span>
                                    {extractImageIdFromFormula(cell) && (
                                      <span className="text-xs mt-1 text-gray-500 truncate max-w-full">
                                        ID: {extractImageIdFromFormula(cell)}
                                      </span>
                                    )}
                                  </div>
                                ) : (
                                  cell ?? ''
                                )}
                              </div>
                            )}
                          </td>
                        );
                      })}

                      {Array.from({ length: Math.max(0, columnCount - row.length) }).map((_, idx) => (
                        <td
                          key={`empty-${idx}`}
                          className="border border-gray-200 bg-gray-50/10"
                          style={{ minWidth: '120px', padding: '10px 16px' }}
                        />
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  const renderSheetTabs = () => {
    if (sheets.length <= 0) return null;

    return (
      <div className="border-t border-gray-300 bg-gray-100 px-2 py-2 flex items-start">
        <div className="flex space-x-1 flex-wrap gap-1.5">
          {sheets.map((sheet) => (
            <button
              key={sheet}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors duration-150 whitespace-nowrap ${
                activeSheet === sheet
                  ? 'bg-white text-blue-600 border border-gray-300 shadow-sm'
                  : 'bg-gray-200 text-gray-700 border border-transparent hover:bg-gray-300'
              }`}
              onClick={() => setActiveSheet(sheet)}
              title={sheet}
            >
              {sheet.length > 15 ? `${sheet.substring(0, 12)}...` : sheet}
            </button>
          ))}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[500px] bg-white rounded-lg border border-gray-200">
        <div className="flex flex-col items-center gap-3">
          <div className="relative">{loadingIcon ?? <DefaultSpinner />}</div>
          <span className="text-sm text-gray-500">{t('loading')}</span>
          <span className="text-xs text-gray-400">{t('supportedFormats')}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="border border-gray-200 rounded-lg bg-white h-full flex flex-col shadow-sm overflow-hidden">
      <div className="flex-1 flex flex-col min-h-0">
        {/* Table content area */}
        <div className="flex-1 min-h-0 flex flex-col p-4">
          {error ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-center p-8">
              <div className="text-red-500 mb-4 p-4 bg-red-50 rounded-lg border border-red-200 max-w-md">
                <svg className="w-12 h-12 mx-auto mb-3 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.732 16.5c-.77.833.192 2.5 1.732 2.5z"
                  />
                </svg>
                <div className="font-semibold text-lg mb-1">{t('previewFailed')}</div>
                <div className="text-sm">{error}</div>
              </div>
              {filePath && (
                <button
                  className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors text-sm font-medium flex items-center btn-brand-primary"
                  onClick={() => window.open(filePath, '_blank')}
                >
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                  {t('downloadOriginal')}
                </button>
              )}
            </div>
          ) : (
            renderContent()
          )}
        </div>
        {renderSheetTabs()}
      </div>
    </div>
  );
}
