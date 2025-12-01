import React, { useState, useEffect, useRef } from "react";
import * as XLSX from "xlsx";
import { LoadingIcon } from "@/components/bs-icons/loading";

const ExcelPreview = ({ filePath }) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sheets, setSheets] = useState([]);
  const [activeSheet, setActiveSheet] = useState("");
  const [excelData, setExcelData] = useState({});
  const tableContainerRef = useRef(null);

  // File type detection
  const fileExt = filePath?.toLowerCase()?.split(".")?.pop() || "";
  const isCSV = fileExt === "csv";
  const isExcel = ["xlsx", "xls"].includes(fileExt);

  // CSV parsing function
  const parseCSV = (csvStr) => {
    try {
      if (!csvStr || typeof csvStr !== 'string') return [];
      
      const lines = csvStr.split(/\r?\n/).filter(line => line && line.trim() !== "");
      const maxRows = 1000;
      const safeLines = lines.slice(0, maxRows);
      
      const rows = [];
      safeLines.forEach(line => {
        const columns = line.split(',').map(col => col.trim());
        if (columns.some(col => col !== '')) {
          rows.push(columns);
        }
      });
      
      return rows;
    } catch (err) {
      console.error("CSV parsing error:", err);
      return [];
    }
  };

  // Clean data - remove empty rows and columns
  const cleanData = (data) => {
    if (!Array.isArray(data) || data.length === 0) return [];
    
    const nonEmptyRows = data.filter(row => 
      Array.isArray(row) && row.some(cell => 
        cell !== undefined && cell !== null && cell !== ''
      )
    );
    
    if (nonEmptyRows.length === 0) return [];
    
    const columnCount = Math.max(...nonEmptyRows.map(row => row.length));
    const hasDataColumns = [];
    
    for (let col = 0; col < columnCount; col++) {
      const hasData = nonEmptyRows.some(row => 
        row[col] !== undefined && row[col] !== null && row[col] !== ''
      );
      if (hasData) hasDataColumns.push(col);
    }
    
    return nonEmptyRows.map(row => 
      hasDataColumns.map(colIndex => row[colIndex] || '')
    );
  };

  useEffect(() => {
    const fetchAndParseFile = async () => {
      try {
        setLoading(true);
        
        if (!filePath) throw new Error("File path is empty");

        const response = await fetch(filePath);
        if (!response.ok) throw new Error(`File loading failed: ${response.status}`);

        if (isCSV) {
          const arrayBuffer = await response.arrayBuffer();
          if (arrayBuffer.byteLength === 0) throw new Error("File content is empty");
          if (arrayBuffer.byteLength > 10 * 1024 * 1024) throw new Error("File is too large");

          const uint8Array = new Uint8Array(arrayBuffer);
          let decodedStr = "";

          const encodings = ["UTF-8", "GBK", "gb2312"];
          for (const encoding of encodings) {
            try {
              const decoder = new TextDecoder(encoding);
              decodedStr = decoder.decode(uint8Array);
              if (decodedStr.charCodeAt(0) === 0xFEFF) decodedStr = decodedStr.slice(1);
              break;
            } catch (e) { continue; }
          }
          
          if (!decodedStr) decodedStr = new TextDecoder().decode(uint8Array);

          let csvData = parseCSV(decodedStr);
          csvData = cleanData(csvData);
          
          setExcelData({ "Sheet1": csvData });
          setSheets(["Sheet1"]);
          setActiveSheet("Sheet1");
        }
        else if (isExcel) {
          const arrayBuffer = await response.arrayBuffer();
          if (arrayBuffer.byteLength === 0) throw new Error("Excel file content is empty");
          if (arrayBuffer.byteLength > 10 * 1024 * 1024) throw new Error("Excel file is too large");

          let workbook;
          try {
            workbook = XLSX.read(arrayBuffer, {
              type: "array",
              cellText: true,
              cellDates: false,
              raw: false,
              dense: true
            });
          } catch (parseError) {
            throw new Error(`Excel parsing failed: ${parseError.message}`);
          }

          const sheetNames = workbook.SheetNames || [];
          const parsedData = {};
          
          const maxSheets = 5;
          const safeSheetNames = sheetNames.slice(0, maxSheets);
          
          safeSheetNames.forEach(sheetName => {
            try {
              const worksheet = workbook.Sheets[sheetName];
              if (!worksheet) {
                parsedData[sheetName] = [];
                return;
              }
              
              const sheetData = XLSX.utils.sheet_to_json(worksheet, { 
                header: 1,
                defval: "",
                blankrows: false
              });
              
              const cleanData = (sheetData || [])
                .map(row => {
                  if (!Array.isArray(row)) return [""];
                  return row.map(cell => {
                    if (cell === undefined || cell === null) return "";
                    return String(cell);
                  });
                })
                .filter(row => row.some(cell => cell !== ""));
              
              parsedData[sheetName] = cleanData;
            } catch (sheetError) {
              console.error(`Error processing sheet ${sheetName}:`, sheetError);
              parsedData[sheetName] = [["Data loading error"]];
            }
          });

          setExcelData(parsedData);
          setSheets(safeSheetNames);
          setActiveSheet(safeSheetNames[0] || "");
        }
        else {
          throw new Error(`Unsupported file type: ${fileExt}, only CSV/XLSX/XLS are supported`);
        }

        setError(null);
      } catch (err) {
        console.error("File parsing failed:", err);
        setError(err.message || "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    if (filePath) fetchAndParseFile();
    else {
      setLoading(false);
      setError("File path is empty");
    }
  }, [filePath, fileExt, isCSV, isExcel]);

  // 计算表格列数
  const getTableColumnCount = (data) => {
    if (!Array.isArray(data) || data.length === 0) return 0;
    return Math.max(...data.map(row => row.length));
  };

  const renderContent = () => {
    const sheetData = excelData[activeSheet];
    
    if (!Array.isArray(sheetData) || sheetData.length === 0) {
      return (
        <div className="flex items-center justify-center h-full text-gray-500">
          No data in current sheet
        </div>
      );
    }

    const maxDisplayRows = 100;
    const displayData = sheetData.slice(0, maxDisplayRows);
    const hasMoreData = sheetData.length > maxDisplayRows;
    const columnCount = getTableColumnCount(displayData);

    return (
      <div className="flex flex-col h-full">
        {hasMoreData && (
          <div className="bg-yellow-50 text-yellow-700 px-4 py-2 text-sm border-b">
            Showing first {maxDisplayRows} rows (total {sheetData.length} rows)
          </div>
        )}
        
        {/* 表格信息栏 */}
        <div className="flex items-center justify-between px-2 py-1 bg-gray-50 border-b text-xs text-gray-500">
          <span>
            Sheet: {activeSheet} | Rows: {displayData.length} | Columns: {columnCount}
          </span>
          {columnCount > 8 && (
            <span className="flex items-center text-orange-600 font-medium">
              <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
              </svg>
              Scroll horizontally to view all columns
            </span>
          )}
        </div>
        
        {/* 修复的滚动容器 - 关键修改：确保容器宽度约束生效 */}
        <div 
          ref={tableContainerRef}
          className="flex-1 overflow-auto border border-gray-200 bg-white relative"
          style={{
            minHeight: "300px",
            maxHeight: "calc(100vh - 200px)",
            width: "100%" // 强制容器继承父宽度
          }}
        >
          {/* 表格容器 - 关键修改：移除inline-block，用width:100%约束 */}
          <div className="w-full">
            {/* 关键修改：添加table-layout: fixed，强制表格宽度由容器决定 */}
            <table className="w-full border-collapse" style={{ tableLayout: "fixed" }}>
              <thead className="bg-gray-50 sticky top-0 z-20">
                <tr>
                  {displayData[0]?.map((header, index) => (
                    <th 
                      key={index}
                      className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border border-gray-200 bg-gray-50 whitespace-nowrap"
                      // 关键修改：降低最小宽度，限制最大宽度
                      style={{
                        minWidth: "80px", 
                        maxWidth: "200px",
                        position: "sticky",
                        top: 0,
                        overflow: "hidden", // 防止表头文本溢出
                        textOverflow: "ellipsis" // 表头长文本省略
                      }}
                    >
                      <div className="flex items-center justify-between">
                        <span className="truncate" title={String(header)}>
                          {String(header || `Column ${index + 1}`)}
                        </span>
                        <span className="text-xs text-gray-400 ml-2 font-normal">
                          {index + 1}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="bg-white">
                {displayData.slice(1).map((row, rowIndex) => (
                  <tr 
                    key={rowIndex} 
                    className={`hover:bg-blue-50 transition-colors ${
                      rowIndex % 2 === 0 ? 'bg-white' : 'bg-gray-50/30'
                    }`}
                  >
                    {row.map((cell, cellIndex) => (
                      <td 
                        key={cellIndex}
                        className="px-3 py-2 text-sm text-gray-900 border border-gray-200 align-top"
                        // 关键修改：与表头宽度保持一致，限制最大宽度
                        style={{
                          minWidth: "80px",
                          maxWidth: "200px",
                          overflow: "hidden" // 防止内容撑开单元格
                        }}
                      >
                        {/* 关键修改：添加word-wrap和overflow-wrap，强制长文本换行 */}
                        <div 
                          className="leading-relaxed"
                          style={{
                            maxHeight: "120px",
                            overflow: "hidden",
                            display: "-webkit-box",
                            WebkitLineClamp: 4,
                            WebkitBoxOrient: "vertical",
                            wordWrap: "break-word", // 强制换行
                            overflowWrap: "anywhere" // 适配长连续文本
                          }}
                          title={cell === undefined || cell === null ? "" : String(cell)}
                        >
                          {cell === undefined || cell === null ? "" : String(cell)}
                        </div>
                      </td>
                    ))}
                    {/* 补充空单元格以确保表格结构完整 */}
                    {Array.from({ length: Math.max(0, columnCount - row.length) }).map((_, idx) => (
                      <td 
                        key={`empty-${idx}`}
                        className="px-3 py-2 border border-gray-200 bg-gray-50/20"
                        style={{ minWidth: "80px", maxWidth: "200px" }}
                      />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 底部提示 */}
        {columnCount > 6 && (
          <div className="mt-2 px-3 py-1 bg-blue-50 border border-blue-200 rounded text-xs text-blue-700 text-center">
            <div className="flex items-center justify-center">
              <svg className="w-4 h-4 mr-2 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4" />
              </svg>
              Use horizontal scroll to view all {columnCount} columns
            </div>
          </div>
        )}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full bg-white rounded-lg border">
        <div className="flex flex-col items-center gap-2">
          <LoadingIcon />
          <span className="text-sm text-gray-500">Loading file...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="border rounded-lg overflow-hidden bg-white h-full flex flex-col">
      <div className="flex-1 flex flex-col p-4">
        {sheets.length > 0 && (
          <div className="flex gap-2 mb-4 overflow-x-auto pb-2 flex-shrink-0">
            {sheets.map((sheet) => (
              <button
                key={sheet}
                className={`px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap ${
                  activeSheet === sheet 
                    ? "bg-blue-500 text-white shadow-sm" 
                    : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                }`}
                onClick={() => setActiveSheet(sheet)}
              >
                {sheet}
              </button>
            ))}
          </div>
        )}

        {error && (
          <div className="flex flex-col items-center justify-center h-full text-center p-8">
            <div className="text-red-500 mb-2">
              Preview failed: {error}
            </div>
            <button
              className="text-blue-500 underline hover:text-blue-700 text-sm"
              onClick={() => window.open(filePath, "_blank")}
            >
              Click to download original file
            </button>
          </div>
        )}

        {!error && renderContent()}
      </div>
    </div>
  );
};

export default ExcelPreview;