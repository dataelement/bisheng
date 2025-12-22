import React, { useState, useEffect, useRef } from "react";
import * as XLSX from "xlsx";
import XlsxPopulate from 'xlsx-populate/browser/xlsx-populate';
import { LoadingIcon } from "@/components/bs-icons/loading";
import { useTranslation } from "react-i18next";

const ExcelPreview = ({ filePath }) => {
  const { t } = useTranslation('knowledge');
console.log(filePath,3);

  // ---------------------- State Management ----------------------
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sheets, setSheets] = useState([]);
  const [activeSheet, setActiveSheet] = useState("");
  const [excelData, setExcelData] = useState({});
  const [images, setImages] = useState([]); // 存储图片数据
  const [imagePositions, setImagePositions] = useState({}); // 图片位置映射
  const tableContainerRef = useRef(null);
  const getFileExtension = (filePath) => {
    if (!filePath) return "";
    
    // 移除查询参数
    const withoutQuery = filePath.split('?')[0];
    
    // 获取扩展名
    const parts = withoutQuery.split('.');
    if (parts.length < 2) return "";
    
    const ext = parts.pop()?.toLowerCase() || "";
    
    // 确保是有效的扩展名
    const validExtensions = ['csv', 'xlsx', 'xls', 'txt'];
    if (validExtensions.includes(ext)) {
      return ext;
    }
    
    return "";
  };
  // ---------------------- File Type Detection ----------------------
  const fileExt = getFileExtension(filePath);
  const isCSV = fileExt === "csv";
  const isExcel = ["xlsx", "xls"].includes(fileExt);
  const isXLSX = fileExt === "xlsx"; // 用于图片提取

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

  // ---------------------- 辅助函数：根据文件扩展名获取MIME类型 ----------------------
  const getMimeType = (ext) => {
    const mimeTypes = {
      'png': 'image/png',
      'jpg': 'image/jpeg',
      'jpeg': 'image/jpeg',
      'gif': 'image/gif',
      'bmp': 'image/bmp',
      'jfif': 'image/jpeg',
      'tiff': 'image/tiff',
      'tif': 'image/tiff',
      'svg': 'image/svg+xml'
    };
    return mimeTypes[ext] || 'image/png';
  };

  // ---------------------- 辅助函数：解析cellimages.xml ----------------------
  const parseCellImagesXml = (xmlString) => {
    const positions = [];
    try {
      const parser = new DOMParser();
      const xmlDoc = parser.parseFromString(xmlString, 'text/xml');
      
      // 尝试不同的节点名称
      const imageNodes = xmlDoc.getElementsByTagName('cellImage') || 
                        xmlDoc.getElementsByTagName('drawing') ||
                        xmlDoc.getElementsByTagName('picture') ||
                        xmlDoc.getElementsByTagName('xdr:twoCellAnchor') ||
                        xmlDoc.getElementsByTagName('xdr:oneCellAnchor');
      
      for (let i = 0; i < imageNodes.length; i++) {
        const node = imageNodes[i];
        
        // 尝试获取单元格位置
        let cellAddress = null;
        let imageId = null;
        
        // 方法1: 从cellImage节点获取
        if (node.tagName === 'cellImage') {
          cellAddress = node.getAttribute('r');
          imageId = node.getAttribute('imageId') || node.getAttribute('id') || node.getAttribute('r:id');
        }
        // 方法2: 从drawing节点获取
        else if (node.tagName === 'drawing' || node.tagName === 'picture') {
          cellAddress = node.getAttribute('cell');
          imageId = node.getAttribute('r:id') || node.getAttribute('id');
        }
        // 方法3: 从xdr命名空间的节点获取（Excel绘图对象）
        else if (node.tagName.includes('Anchor')) {
          // 尝试从from节点获取起始位置
          const from = node.getElementsByTagName('xdr:from')[0];
          if (from) {
            const colNode = from.getElementsByTagName('xdr:col')[0];
            const rowNode = from.getElementsByTagName('xdr:row')[0];
            if (colNode && rowNode) {
              const col = parseInt(colNode.textContent, 10);
              const row = parseInt(rowNode.textContent, 10) + 1; // Excel行从1开始
              const colLetter = numberToColumnLetters(col);
              cellAddress = `${colLetter}${row}`;
            }
          }
          
          // 获取图片引用
          const pic = node.getElementsByTagName('xdr:pic')[0];
          if (pic) {
            const blip = pic.getElementsByTagName('a:blip')[0];
            if (blip) {
              imageId = blip.getAttribute('r:embed') || blip.getAttribute('embed');
            }
          }
        }
        
        if (cellAddress && imageId) {
          positions.push({
            cellAddress: cellAddress,
            imageId: imageId.replace('rId', '') // 移除rId前缀
          });
        }
      }
    } catch (e) {
      console.warn('Failed to parse cellimages.xml:', e);
    }
    
    console.log('Parsed image positions:', positions);
    return positions;
  };

  // ---------------------- Data Fetching and Parsing ----------------------
  useEffect(() => {
    const fetchAndParseFile = async () => {
      try {
        setLoading(true);
        setImages([]); // 重置图片
        setImagePositions({}); // 重置图片位置
        if (!filePath) throw new Error(t('filePathEmpty'));

        const response = await fetch(filePath);
        if (!response.ok) throw new Error(`${t('fileLoadFailed')}: ${response.status}`);
        console.log(`File loaded successfully: ${response}`);

        const arrayBuffer = await response.arrayBuffer();
        
        if (isCSV) {
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
          // 并行处理：SheetJS处理数据 + xlsx-populate处理图片
          await Promise.all([
            // 1. 使用SheetJS读取数据（保持原有逻辑）
            (async () => {
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
            })(),

            // 2. 使用xlsx-populate提取图片（新增）
            (async () => {
              try {
                // 只处理xlsx文件（xls格式支持有限）
                if (isXLSX) {
                  const workbook = await XlsxPopulate.fromDataAsync(arrayBuffer);
                  const extractedImages = [];
                  const positionMap = {};
                  
                  console.log('Workbook loaded:', workbook);
                  console.log('Number of sheets:', workbook.sheets().length);
                  
                  // 直接访问内部的 JSZip 对象来提取图片
                  const zip = workbook._zip;
                  console.log('Zip files:', Object.keys(zip.files));
                  
                  // 查找所有图片文件（通常存储在xl/media/目录下）
                  const mediaFiles = [];
                  zip.forEach((relativePath, zipEntry) => {
                    if (relativePath.startsWith('xl/media/') && 
                        !zipEntry.dir && 
                        ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'jfif', 'tiff', 'tif'].some(ext => 
                          relativePath.toLowerCase().endsWith(`.${ext}`)
                        )) {
                      mediaFiles.push({
                        path: relativePath,
                        name: zipEntry.name,
                        ext: relativePath.split('.').pop().toLowerCase(),
                        zipEntry: zipEntry
                      });
                    }
                  });
                  
                  console.log('Found media files:', mediaFiles);
                  
                  // 提取图片数据
                  for (const file of mediaFiles) {
                    try {
                      const content = await zip.file(file.path).async('base64');
                      const imageIndex = extractedImages.length;
                      extractedImages.push({
                        id: `image_${imageIndex}`,
                        sheet: 'Sheet1', // 默认，可以后续尝试关联具体工作表
                        base64: content,
                        mimeType: getMimeType(file.ext),
                        path: file.path,
                        fileName: file.name.split('/').pop(),
                        ext: file.ext
                      });
                    } catch (e) {
                      console.warn(`Failed to extract image ${file.path}:`, e);
                    }
                  }
                  
                  // 尝试解析 cellimages.xml 获取图片位置信息
                  try {
                    const cellImagesXml = await zip.file('xl/cellimages.xml')?.async('string');
                    if (cellImagesXml) {
                      console.log('Found cellimages.xml, length:', cellImagesXml.length);
                      const positions = parseCellImagesXml(cellImagesXml);
                      
                      // 将位置信息映射到图片
                      positions.forEach(pos => {
                        // 查找匹配的图片（通过文件名或路径）
                        const matchedImage = extractedImages.find(img => {
                          // 尝试通过多种方式匹配
                          return img.path.includes(pos.imageId) ||
                                 img.fileName.includes(pos.imageId) ||
                                 pos.imageId.includes(img.ext) ||
                                 img.id === `image_${pos.imageId}`;
                        });
                        
                        if (matchedImage && pos.cellAddress) {
                          // 更新图片的工作表信息
                          matchedImage.cellAddress = pos.cellAddress;
                          
                          // 构建位置映射
                          if (!positionMap[pos.cellAddress]) {
                            positionMap[pos.cellAddress] = [];
                          }
                          positionMap[pos.cellAddress].push(matchedImage.id);
                        }
                      });
                    }
                  } catch (e) {
                    console.warn('Failed to parse cellimages.xml:', e);
                    
                    // 尝试解析其他可能的位置文件
                    try {
                      // 查找所有可能包含位置信息的文件
                      const drawingFiles = [];
                      zip.forEach((relativePath, zipEntry) => {
                        if (relativePath.includes('drawing') && relativePath.endsWith('.xml') && !zipEntry.dir) {
                          drawingFiles.push(relativePath);
                        }
                      });
                      
                      console.log('Found drawing files:', drawingFiles);
                      
                      // 尝试解析每个drawing文件
                      for (const drawingPath of drawingFiles) {
                        try {
                          const drawingXml = await zip.file(drawingPath)?.async('string');
                          if (drawingXml) {
                            const positions = parseCellImagesXml(drawingXml);
                            console.log(`Parsed positions from ${drawingPath}:`, positions);
                          }
                        } catch (drawingErr) {
                          console.warn(`Failed to parse ${drawingPath}:`, drawingErr);
                        }
                      }
                    } catch (drawingSearchErr) {
                      console.warn('Failed to search for drawing files:', drawingSearchErr);
                    }
                  }
                  
                  // 如果没有从XML解析到位置，尝试通过工作表关系查找
                  if (extractedImages.length > 0 && Object.keys(positionMap).length === 0) {
                    console.log('No position info found in XML, trying to map by sheet relationships...');
                    
                    // 遍历所有工作表，检查是否有drawing关系
                    workbook.sheets().forEach(sheet => {
                      try {
                        const sheetRels = sheet._relationships;
                        if (sheetRels && sheetRels._node && sheetRels._node.children) {
                          console.log(`Relationships for sheet ${sheet.name()}:`, sheetRels._node.children);
                        }
                      } catch (e) {
                        console.warn(`Failed to get relationships for sheet ${sheet.name()}:`, e);
                      }
                    });
                  }
                  
                  setImages(extractedImages);
                  setImagePositions(positionMap);
                  
                  if (extractedImages.length > 0) {
                    console.log(`通过xlsx-populate提取到 ${extractedImages.length} 张图片`, extractedImages);
                    console.log('图片位置映射:', positionMap);
                  }
                }
              } catch (populateErr) {
                console.warn('Failed to extract images with xlsx-populate:', populateErr);
                // 不影响主要功能，图片提取失败不会阻止表格显示
              }
            })()
          ]);

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

  // ---------------------- 将单元格地址转换为行列索引 ----------------------
  const cellAddressToIndices = (address) => {
    // 将Excel单元格地址如 "A1" 转换为行列索引
    const match = address.match(/^([A-Z]+)(\d+)$/);
    if (!match) return null;
    
    const colLetters = match[1];
    const rowNum = parseInt(match[2], 10);
    
    // 转换列字母为列索引（0-based）
    let colNum = 0;
    for (let i = 0; i < colLetters.length; i++) {
      colNum = colNum * 26 + (colLetters.charCodeAt(i) - 64);
    }
    
    return { row: rowNum - 1, col: colNum - 1 }; // 转换为0-based索引
  };

  // ---------------------- 计算单元格尺寸 ----------------------
  const getCellDimensions = () => {
    // 根据屏幕尺寸调整单元格尺寸
    let cellWidth, cellHeight, headerHeight;
    
    switch (screenSize) {
      case "small":
        cellWidth = 100;
        cellHeight = 35;
        headerHeight = 45;
        break;
      case "large":
        cellWidth = 150;
        cellHeight = 45;
        headerHeight = 55;
        break;
      default:
        cellWidth = 120;
        cellHeight = 40;
        headerHeight = 50;
    }
    
    return { cellWidth, cellHeight, headerHeight };
  };

  // ---------------------- 从DISPIMG公式中提取图片ID ----------------------
  const extractImageIdFromFormula = (formula) => {
    if (!formula || typeof formula !== 'string') return null;
    
    // 尝试多种匹配模式
    const patterns = [
      /DISPIMG\("([^"]+)"\)/i,
      /DISPIMG\('([^']+)'\)/i,
      /DISPIMG\("([^"]+)",\s*\d+\)/i,
      /DISPIMG\('([^']+)',\s*\d+\)/i
    ];
    
    for (const pattern of patterns) {
      const match = formula.match(pattern);
      if (match && match[1]) {
        return match[1];
      }
    }
    
    return null;
  };

  // ---------------------- 获取单元格对应的图片 ----------------------
  const getCellImage = (rowIndex, colIndex, cellContent) => {
    // 方法1: 通过单元格地址查找
    const cellAddress = `${numberToColumnLetters(colIndex)}${rowIndex + 1}`;
    const imageIds = imagePositions[cellAddress];
    
    if (imageIds && imageIds.length > 0) {
      return images.find(img => img.id === imageIds[0]);
    }
    
    // 方法2: 通过DISPIMG公式查找
    if (cellContent && typeof cellContent === 'string' && cellContent.startsWith('=DISPIMG')) {
      const imageId = extractImageIdFromFormula(cellContent);
      if (imageId) {
        // 尝试通过图片ID查找
        const imageById = images.find(img => 
          img.path.includes(imageId) ||
          img.fileName.includes(imageId) ||
          imageId.includes(img.ext) ||
          (img.id && img.id.includes(imageId))
        );
        
        if (imageById) return imageById;
        
        // 如果没有找到，返回第一张图片作为占位
        if (images.length > 0) return images[0];
      }
    }
    
    return null;
  };

  // ---------------------- 渲染表格内容 ----------------------
  const renderContent = () => {
    const sheetData = excelData[activeSheet];
    if (!Array.isArray(sheetData) || sheetData.length === 0) {
      return (
        <div 
        className="flex items-center justify-center text-gray-500"
        style={{
          minHeight: screenSize === "small" ? "520px" : "684px"
        }}
      >
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
      <div className={`flex flex-col relative`}>
        <div
          ref={tableContainerRef}
          className="flex-1 border border-gray-200 bg-white relative overflow-auto"
          style={{
            minHeight: screenSize === "small" ? "480px" : "684px",
            maxHeight: "calc(100vh - 300px)",
            width: "100%",
            maxWidth: getTableContainerMaxWidth(),
            overflowX: "auto",
          }}
        >
          <div className="min-w-full">
            <table className="min-w-full border-collapse">
              <thead className="bg-gray-50">
                 {/* Column letters row */}
                <tr>
                  <th 
                    className="border border-gray-200 bg-gray-100 text-gray-600 text-xs font-medium"
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
                    className="border border-gray-200 bg-gray-50 text-gray-700 text-xs font-medium"
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
                {displayData.slice(1).map((row, rowIndex) => {
                  const actualRowIndex = rowIndex + 1; // 因为slice(1)，实际行索引要+1
                  
                  return (
                    <tr
                      key={rowIndex}
                      className={`hover:bg-blue-50 transition-colors duration-150 ${
                        rowIndex % 2 === 0 ? "bg-white" : "bg-gray-50/30"
                      }`}
                    >
                      {/* 行号单元格 */}
                      <td 
                        className="border border-gray-200 bg-gray-50 text-gray-600 text-xs font-medium text-center sticky left-0 z-5"
                        style={{
                          minWidth: "60px",
                          maxWidth: "60px",
                          padding: "10px 8px",
                          boxShadow: "2px 0 0 #e5e7eb"
                        }}
                      >
                        {actualRowIndex}
                      </td>
                      
                      {/* 数据单元格 */}
                      {row.map((cell, cellIndex) => {
                        const cellImage = getCellImage(actualRowIndex, cellIndex, cell);
                        const isImageCell = cellImage !== null;
                        
                        return (
                          <td
                            key={cellIndex}
                            className="text-sm text-gray-800 border border-gray-200 align-top"
                            style={{
                              minWidth: `${columnWidths[cellIndex + 1] || 200}px`,
                              maxWidth: "400px",
                              padding: isImageCell ? "2px" : "10px 16px",
                              wordBreak: "break-word",
                              position: 'relative',
                              backgroundColor: isImageCell ? '#f0f9ff' : 'transparent',
                              verticalAlign: isImageCell ? 'middle' : 'top',
                              height: isImageCell ? '120px' : 'auto'
                            }}
                          >
                            {isImageCell && cellImage ? (
                              <div 
                                className="flex items-center justify-center p-1 h-full"
                                style={{
                                  minHeight: "100px",
                                  width: "100%"
                                }}
                              >
                                <img
                                  src={`data:${cellImage.mimeType};base64,${cellImage.base64}`}
                                  alt={`图片 ${actualRowIndex}-${cellIndex + 1}`}
                                  className="max-w-full max-h-full object-contain"
                                  onError={(e) => {
                                    e.target.style.display = 'none';
                                    const parent = e.target.parentElement;
                                    const imageId = extractImageIdFromFormula(cell);
                                    parent.innerHTML = `
                                      <div class="flex flex-col items-center justify-center p-2 text-gray-500 text-xs h-full w-full">
                                        <svg class="w-6 h-6 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                        </svg>
                                        <span>图片加载失败</span>
                                        ${imageId ? `<span class="text-xs mt-1 text-center">ID: ${imageId}</span>` : ''}
                                      </div>
                                    `;
                                  }}
                                  onLoad={(e) => {
                                    console.log(`Image loaded successfully: ${actualRowIndex}-${cellIndex}`);
                                  }}
                                />
                              </div>
                            ) : (
                              <div
                                className="leading-relaxed"
                                style={{
                                  maxHeight: "150px",
                                  overflow: "auto",
                                  lineHeight: "1.6"
                                }}
                              >
                                {cell && typeof cell === 'string' && cell.startsWith('=DISPIMG') ? (
                                  <div className="flex flex-col items-center justify-center p-2 text-blue-600 text-xs bg-blue-50 rounded border border-blue-200 min-h-[80px]">
                                    <svg className="w-5 h-5 mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                    </svg>
                                    <span className="text-center">图片引用</span>
                                    {extractImageIdFromFormula(cell) && (
                                      <span className="text-xs mt-1 text-gray-500 truncate max-w-full">
                                        ID: {extractImageIdFromFormula(cell)}
                                      </span>
                                    )}
                                  </div>
                                ) : (
                                  cell ?? ""
                                )}
                              </div>
                            )}
                          </td>
                        );
                      })}
                      
                      {/* 填充空单元格 */}
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
                  );
                })}
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
    <div className="border-t border-gray-300 bg-gray-100 px-2 py-2 flex items-start">
      <div className="flex space-x-1 flex-wrap gap-1.5"> 
        {sheets.map((sheet) => (
          <button
            key={sheet}
            className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors duration-150 whitespace-nowrap ${
              activeSheet === sheet
                ? "bg-white text-blue-600 border border-gray-300 shadow-sm" 
                : "bg-gray-200 text-gray-700 border border-transparent hover:bg-gray-300"
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
            <LoadingIcon className="w-8 h-8 text-blue-500" />
          </div>
          <span className="text-sm text-gray-500">{t('loading')}</span>
          <span className="text-xs text-gray-400">{t('supportedFormats')}</span>
        </div>
      </div>
    );
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