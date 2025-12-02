import React, { useState, useEffect, useRef } from "react";
import * as XLSX from "xlsx";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { useTranslation } from "react-i18next";


const ExcelPreview = ({ filePath }) => {
  const { t } = useTranslation('knowledge');

  // ---------------------- State Management ----------------------
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sheets, setSheets] = useState([]);
  const [activeSheet, setActiveSheet] = useState("");
  const [excelData, setExcelData] = useState({});
  const tableContainerRef = useRef(null);

  // ---------------------- File Type Detection ----------------------
  const fileExt = filePath?.toLowerCase()?.split(".")?.pop() || "";
  const isCSV = fileExt === "csv";
  const isExcel = ["xlsx", "xls"].includes(fileExt);

  // ---------------------- Screen Size Detection (Adapt to Small/Large Screens) ----------------------
  const [screenSize, setScreenSize] = useState("medium"); // small/medium/large

  useEffect(() => {
    const handleResize = () => {
      const width = window.innerWidth;
      if (width <= 1680) setScreenSize("small");
      else if (width >= 1920) setScreenSize("large");
      else setScreenSize("medium");
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // ---------------------- Get Max Width for Table Container ----------------------
  const getTableContainerMaxWidth = () => {
    switch (screenSize) {
      case "small": return "600px";
      case "large": return "1300px";
      default: return "900px";
    }
  };

  // ---------------------- Data Fetching and Parsing ----------------------
  useEffect(() => {
    const fetchAndParseFile = async () => {
      try {
        setLoading(true);
        if (!filePath) throw new Error(t('filePathEmpty'));

        const response = await fetch(filePath);
        if (!response.ok) throw new Error(`${t('fileLoadFailed')}: ${response.status}`);
        console.log(`File loaded successfully: ${response}`);

        if (isCSV) {
          const arrayBuffer = await response.arrayBuffer();
          if (arrayBuffer.byteLength === 0) throw new Error(t('fileContentEmpty'));

          const uint8Array = new Uint8Array(arrayBuffer);
          let decodedStr = "";

          // Try multiple encodings
          const encodings = ["utf-8", "gbk", "gb2312", "gb18030", "big5", "shift_jis"];
          for (const encoding of encodings) {
            try {
              const decoder = new TextDecoder(encoding, { fatal: true });
              decodedStr = decoder.decode(uint8Array);
              if (decodedStr.charCodeAt(0) === 0xfeff) decodedStr = decodedStr.slice(1);
              break;
            } catch (e) { continue; }
          }

          if (!decodedStr) decodedStr = new TextDecoder().decode(uint8Array);
          const csvData = parseCSV(decodedStr);
          const cleanedData = cleanData(csvData);

          setExcelData({ "Sheet1": cleanedData });
          setSheets(["Sheet1"]);
          setActiveSheet("Sheet1");

        } else if (isExcel) {
          const arrayBuffer = await response.arrayBuffer();
          if (arrayBuffer.byteLength === 0) throw new Error(t('excelContentEmpty'));
          const workbook = XLSX.read(arrayBuffer, {
            type: "array",
            cellText: true,
            cellDates: true,
            raw: false,
            dense: true
          });

          const sheetNames = workbook.SheetNames || [];
          const safeSheets = sheetNames;
          const parsedData = {};

          safeSheets.forEach(sheetName => {
            try {
              const worksheet = workbook.Sheets[sheetName];
              if (!worksheet) {
                parsedData[sheetName] = [];
                return;
              }

              const range = XLSX.utils.decode_range(worksheet['!ref'] || "A1");
              worksheet['!ref'] = XLSX.utils.encode_range(range);

              const sheetData = XLSX.utils.sheet_to_json(worksheet, {
                header: 1,
                defval: "",
                blankrows: false,
                raw: false
              });
              console.log(`Sheet ${sheetName} parsed result (2D array):`, sheetData);
              const cleanedData = cleanData(
                sheetData.map(row => Array.isArray(row) ? row : [])
              );

              parsedData[sheetName] = cleanedData;
            } catch (sheetErr) {
              console.error(`Failed to parse Sheet ${sheetName}:`, sheetErr);
              parsedData[sheetName] = [[t('sheetParseError')]];
            }
          });

          setExcelData(parsedData);
          setSheets(safeSheets);
          setActiveSheet(safeSheets[0] || "");

        } else {
          throw new Error(t('unsupportedType', { type: fileExt }));
        }

        setError(null);
      } catch (err) {
        console.error("File parsing failed:", err);
        setError(err.message || t('unknownError'));
      } finally {
        setLoading(false);
      }
    };

    if (filePath) fetchAndParseFile();
    else {
      setLoading(false);
      setError(t('filePathEmpty'));
    }
  }, [filePath, t]);

  // ---------------------- CSV Parsing Function ----------------------
  const parseCSV = (csvStr) => {
    console.log(csvStr, 2);

    try {
      if (!csvStr || typeof csvStr !== "string") return [];
      const lines = csvStr.split(/\r?\n/).filter(line => line.trim() !== "");
      const safeLines = lines; // No row limit
      const rows = [];
      const delimiters = [',', '\t', ';', '|'];

      // Auto-detect best delimiter
      let detectedDelimiter = ',';
      let maxColumns = 0;

      for (const delimiter of delimiters) {
        const testRow = safeLines[0]?.split(delimiter) || [];
        if (testRow.length > maxColumns && testRow.some(col => col.trim() !== "")) {
          maxColumns = testRow.length;
          detectedDelimiter = delimiter;
        }
      }

      safeLines.forEach(line => {
        const columns = line.split(detectedDelimiter).map(col =>
          col.replace(/^[\"\']|[\"\']$/g, "").trim()
        );
        if (columns.some(col => col !== "")) rows.push(columns);
      });
      console.log("CSV parsed result (2D array):", rows);
      return rows;
    } catch (err) {
      console.error("CSV parsing error:", err);
      return [];
    }
  };

  // ---------------------- Data Cleaning Function ----------------------
  const cleanData = (data) => {
    if (!Array.isArray(data) || data.length === 0) return [];

    // Filter empty rows
    const nonEmptyRows = data.filter(row =>
      row.some(cell =>
        cell !== undefined && cell !== null && cell.toString().trim() !== ""
      )
    );

    if (nonEmptyRows.length === 0) return [];

    // Calculate max column count
    const columnCount = Math.max(...nonEmptyRows.map(row => row.length));

    // Filter columns with data
    const hasDataColumns = [];
    for (let col = 0; col < columnCount; col++) {
      const hasData = nonEmptyRows.some(row =>
        row[col] !== undefined && row[col] !== null && row[col].toString().trim() !== ""
      );
      if (hasData) hasDataColumns.push(col);
    }

    // Keep only columns with data
    return nonEmptyRows.map(row =>
      hasDataColumns.map(colIndex =>
        row[colIndex] ? String(row[colIndex]).trim() : ""
      )
    );
  };

  // ---------------------- Calculate Table Column Count ----------------------
  const getTableColumnCount = (data) => {
    if (!Array.isArray(data) || data.length === 0) return 0;
    return Math.max(...data.map(row => row.length));
  };

  // ---------------------- Convert Number to Column Letters (A, B, C, ..., Z, AA, AB, ...) ----------------------
  const numberToColumnLetters = (num) => {
    let result = '';
    while (num >= 0) {
      result = String.fromCharCode(65 + (num % 26)) + result;
      num = Math.floor(num / 26) - 1;
    }
    return result;
  };

  // ---------------------- Render Table Content ----------------------
  const renderContent = () => {
    const sheetData = excelData[activeSheet];
    if (!Array.isArray(sheetData) || sheetData.length === 0) {
      return (
        <div className="flex items-center justify-center h-full text-gray-500">
          {t('currentSheetNoData')}
        </div>
      );
    }

    const displayData = [...sheetData];
    const columnCount = getTableColumnCount(displayData);

    // Dynamically calculate column widths
    const calculateColumnWidths = () => {
      const widths = [];
      if (displayData.length > 0 && columnCount > 0) {
        // Fixed width for row number column
        widths.push(60);
        
        for (let i = 0; i < columnCount; i++) {
          const maxLength = displayData.reduce((max, row) => {
            const cell = row[i] || "";
            const cellLength = String(cell).length;
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
      <div className="flex flex-col h-full">
        <div
          ref={tableContainerRef}
          className="flex-1 overflow-auto border border-gray-200 bg-white"
          style={{
            minHeight: "400px",
            maxHeight: "calc(100vh - 300px)",
            width: "100%",
            maxWidth: getTableContainerMaxWidth(),
            overflowX: "auto"
          }}
        >
          <div className="min-w-full">
            <table className="min-w-full border-collapse">
              <thead className="bg-gray-50 sticky top-0 z-20">
                {/* Column letters row */}
                <tr>
                  <th 
                    className="border border-gray-200 bg-gray-100 text-gray-600 text-xs font-medium sticky left-0 z-10"
                    style={{
                      minWidth: "60px",
                      maxWidth: "60px",
                      padding: "8px 4px",
                      textAlign: "center"
                    }}
                  >
                    {/* Top-left empty cell */}
                  </th>
                  {Array.from({ length: columnCount }).map((_, index) => (
                    <th
                      key={`col-header-${index}`}
                      className="border border-gray-200 bg-gray-100 text-gray-600 text-xs font-medium text-center"
                      style={{
                        minWidth: `${columnWidths[index + 1] || 200}px`,
                        maxWidth: "400px",
                        padding: "8px 4px"
                      }}
                    >
                      {numberToColumnLetters(index)}
                    </th>
                  ))}
                </tr>
                
                {/* Data header row */}
                <tr>
                  <th 
                    className="border border-gray-200 bg-gray-50 text-gray-700 text-xs font-medium sticky left-0 z-10"
                    style={{
                      minWidth: "60px",
                      maxWidth: "60px",
                      padding: "12px 8px",
                      textAlign: "center",
                      boxShadow: "2px 0 0 #e5e7eb"
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
                        maxWidth: "400px",
                        padding: "12px 16px",
                        boxShadow: "0 1px 0 #e5e7eb"
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
                {displayData.slice(1).map((row, rowIndex) => (
                  <tr
                    key={rowIndex}
                    className={`hover:bg-blue-50 transition-colors duration-150 ${
                      rowIndex % 2 === 0 ? "bg-white" : "bg-gray-50/30"
                    }`}
                  >
                    {/* Row number cell */}
                    <td 
                      className="border border-gray-200 bg-gray-50 text-gray-600 text-xs font-medium text-center sticky left-0 z-10"
                      style={{
                        minWidth: "60px",
                        maxWidth: "60px",
                        padding: "10px 8px",
                        boxShadow: "2px 0 0 #e5e7eb"
                      }}
                    >
                      {rowIndex + 1}
                    </td>
                    
                    {/* Data cells */}
                    {row.map((cell, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="text-sm text-gray-800 border border-gray-200 align-top"
                        style={{
                          minWidth: `${columnWidths[cellIndex + 1] || 200}px`,
                          maxWidth: "400px",
                          padding: "10px 16px",
                          wordBreak: "break-word"
                        }}
                      >
                        <div
                          className="leading-relaxed"
                          style={{
                            maxHeight: "150px",
                            overflow: "auto",
                            lineHeight: "1.6"
                          }}
                        >
                          {cell ?? ""}
                        </div>
                      </td>
                    ))}
                    
                    {/* Fill empty cells */}
                    {Array.from({
                      length: Math.max(0, columnCount - row.length)
                    }).map((_, idx) => (
                      <td
                        key={`empty-${idx}`}
                        className="border border-gray-200 bg-gray-50/10"
                        style={{
                          minWidth: "120px",
                          padding: "10px 16px"
                        }}
                      />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  };

  // ---------------------- Render Sheet Tabs ----------------------
  const renderSheetTabs = () => {
    if (sheets.length <= 0) return null;

    return (
      <div className="border-t border-gray-300 bg-gray-100 px-2 py-1 flex items-center overflow-x-auto">
        <div className="flex space-x-1">
          {sheets.map((sheet) => (
            <button
              key={sheet}
              className={`px-3 py-1.5 text-sm font-medium rounded-t-md border border-b-0 transition-colors duration-150 whitespace-nowrap ${
                activeSheet === sheet
                  ? "bg-white text-blue-600 border-gray-300 border-b-white -mb-px relative z-10"
                  : "bg-gray-200 text-gray-700 border-transparent hover:bg-gray-300"
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

  // ---------------------- Loading/Error States ----------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[500px] bg-white rounded-lg border border-gray-200">
        <div className="flex flex-col items-center gap-3">
          <div className="relative">
            <LoadingIcon className="w-8 h-8 text-blue-500 animate-spin" />
          </div>
          <span className="text-sm text-gray-500">{t('loading')}</span>
          <span className="text-xs text-gray-400">{t('supportedFormats')}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="border border-gray-200 rounded-lg bg-white h-full flex flex-col shadow-sm">
      <div className="flex-1 flex flex-col">

        {/* Table content area */}
        <div className="flex-1 p-4">
          {error ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-center p-8">
              <div className="text-red-500 mb-4 p-4 bg-red-50 rounded-lg border border-red-200 max-w-md">
                <svg className="w-12 h-12 mx-auto mb-3 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
                <div className="font-semibold text-lg mb-1">{t('previewFailed')}</div>
                <div className="text-sm">{error}</div>
              </div>
              {filePath && (
                <button
                  className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors text-sm font-medium flex items-center"
                  onClick={() => window.open(filePath, "_blank")}
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
};

export default ExcelPreview;