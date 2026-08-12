import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import * as XLSX from 'xlsx';
import XlsxPopulate from 'xlsx-populate/browser/xlsx-populate';
import { ImageGallery } from './ImageGallery';
import {
  cleanData,
  extractImageIdFromFormula,
  getFileExtension,
  getTableColumnCount,
  numberToColumnLetters,
  parseCSV,
} from './sheetUtils';
import type { ExtractedImage, ResolvedImage, SheetData, SheetImageIndex } from './types';
import { extractSheetImages } from './xlsxImages';

export interface ExcelPreviewProps {
  filePath: string;
  /** Prefer passing the extension from the parent; falls back to URL parsing. */
  fileExt?: string;
  /** Brand loading indicator; defaults to a neutral spinner. */
  loadingIcon?: ReactNode;
}

interface SheetCoordinateMaps {
  rowMap: number[];
  colMap: number[];
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
  const [sheetMaps, setSheetMaps] = useState<Record<string, SheetCoordinateMaps>>({});
  const [images, setImages] = useState<ExtractedImage[]>([]);
  const [sheetImages, setSheetImages] = useState<SheetImageIndex>({});
  const tableContainerRef = useRef<HTMLDivElement>(null);

  const fileExt = fileExtProp || getFileExtension(filePath);
  const isCSV = fileExt === 'csv';
  const isXLSX = fileExt === 'xlsx' || fileExt === 'et';

  /**
   * Resolve the active sheet's pictures against the rendered grid. Anchors address
   * the original grid, while cleanData() has dropped blank rows/columns — so the
   * anchor coordinates are translated back through the row/column maps. Anything
   * that lands outside the used range is shown below the table instead of silently
   * disappearing.
   */
  const { placedImages, looseImages } = useMemo(() => {
    const placed = new Map<string, ExtractedImage>();
    const loose: ResolvedImage[] = [];
    const anchors = sheetImages[activeSheet];
    if (!anchors?.length) return { placedImages: placed, looseImages: loose };

    const maps = sheetMaps[activeSheet];
    const toRendered = (originals: number[] | undefined) =>
      new Map((originals ?? []).map((original, rendered): [number, number] => [original, rendered]));
    const rowIndexOf = toRendered(maps?.rowMap);
    const colIndexOf = toRendered(maps?.colMap);

    for (const anchor of anchors) {
      const image = images.find((img) => img.id === anchor.imageId);
      if (!image) continue;

      const row = anchor.floating ? undefined : rowIndexOf.get(anchor.from.row);
      const col = anchor.floating ? undefined : colIndexOf.get(anchor.from.col);
      if (row === undefined || col === undefined) {
        loose.push({ image, anchor });
        continue;
      }
      placed.set(`${row}:${col}`, image);
    }

    return { placedImages: placed, looseImages: loose };
  }, [sheetImages, sheetMaps, images, activeSheet]);

  const getCellImage = useCallback(
    (rowIndex: number, colIndex: number, cellContent: string): ExtractedImage | null => {
      const anchored = placedImages.get(`${rowIndex}:${colIndex}`);
      if (anchored) return anchored;

      // WPS keeps in-cell pictures as a =DISPIMG("ID_...") formula, not a drawing anchor.
      if (typeof cellContent === 'string' && cellContent.startsWith('=DISPIMG')) {
        const imageId = extractImageIdFromFormula(cellContent);
        if (imageId) {
          return images.find((img) => img.path.includes(imageId) || img.id === imageId) ?? null;
        }
      }

      return null;
    },
    [placedImages, images],
  );

  useEffect(() => {
    const fetchAndParseFile = async () => {
      try {
        setLoading(true);
        setImages([]);
        setSheetImages({});
        setExcelData({});
        setSheetMaps({});
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

          const cleaned = cleanData(parseCSV(decodedStr));
          setExcelData({ Sheet1: cleaned.data });
          setSheetMaps({ Sheet1: { rowMap: cleaned.rowMap, colMap: cleaned.colMap } });
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
          const parsedMaps: Record<string, SheetCoordinateMaps> = {};
          sheetNames.forEach((sheetName) => {
            const aoa = XLSX.utils.sheet_to_json(wb.Sheets[sheetName], {
              header: 1,
              defval: '',
            }) as unknown[][];
            const cleaned = cleanData(aoa);
            parsedData[sheetName] = cleaned.data;
            parsedMaps[sheetName] = { rowMap: cleaned.rowMap, colMap: cleaned.colMap };
          });
          setExcelData(parsedData);
          setSheetMaps(parsedMaps);
          setSheets(sheetNames);
          setActiveSheet(sheetNames[0] || '');

          // 2. Image extraction is best-effort; failure must not block table rendering.
          //    Only attempt for .xlsx/.et — xlsx-populate cannot read legacy .xls.
          if (isXLSX) {
            try {
              const workbook = await XlsxPopulate.fromDataAsync(arrayBuffer);
              const extracted = await extractSheetImages(workbook._zip);
              setImages(extracted.images);
              setSheetImages(extracted.index);
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
      // A sheet can legitimately hold pictures and no cells at all.
      if (looseImages.length > 0) {
        return (
          <div className="flex-1 min-h-0 overflow-auto border border-gray-200 bg-white p-4">
            <ImageGallery items={looseImages} />
          </div>
        );
      }
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

            {looseImages.length > 0 && (
              <div className="border-t border-gray-200 p-4">
                <ImageGallery items={looseImages} title={t('imagesOutsideTable')} />
              </div>
            )}
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
