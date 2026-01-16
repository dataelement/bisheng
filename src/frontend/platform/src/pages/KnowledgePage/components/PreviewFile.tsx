import FileView from "@/components/bs-comp/FileView";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { cn } from "@/utils";
import { Info } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useKnowledgeStore from "../useKnowledgeStore";
import DocxPreview from "./DocxFileViewer";
import { convertJsonData } from "./ParagraphEdit";
import { Partition } from "./PreviewResult";
import TxtFileViewer from "./TxtFileViewer";
import ExcelPreview from "./ExcelPreview";

export default function PreviewFile({
  urlState,
  file,
  partitions,
  chunks,
  rawFiles,
  step,
  setChunks,
  edit = false,
  resultFiles,
  etl,
  previewUrl
}: {
  urlState: { load: boolean; url: string };
  file: any;
  partitions: Partition;
  chunks: any;
  rawFiles: any[];
  setChunks: any;
  edit?: boolean;
}) {
  const { t } = useTranslation('knowledge')
  const MemoizedFileView = React.memo(FileView);
  const selectedChunkIndex = useKnowledgeStore((state) => state.selectedChunkIndex);
  const selectedChunkDistanceFactor = useKnowledgeStore((state) => state.selectedChunkDistanceFactor);
  const setNeedCoverData = useKnowledgeStore((state) => state.setNeedCoverData);
  const setSelectedBbox = useKnowledgeStore((state) => state.setSelectedBbox);

  // 1. 统一文件匹配和类型判断逻辑（与ParagraphEdit完全对齐）
  const matchedRawFile = useMemo(() => {
    if (!rawFiles?.length || !file?.id) return null;
    return rawFiles.find(raw => raw.id === file.id);
  }, [rawFiles, file]);

  const targetFile = matchedRawFile || file;
  let fileParseType = '';
  if (step === 2) {
    fileParseType = resultFiles[0].isEtl4lm
  } else if (step === 3 && etl) {
    fileParseType = etl
  } else {
    fileParseType = targetFile.fileType;
  }

  const suffix = useMemo(() => {
    return urlState.url?.split('?')[0].split('/').pop()?.split('.')[1].toLowerCase() || '';
  }, [urlState.url]);

  const isUnsType = useMemo(() => {
    return fileParseType === 'uns' ||
      (targetFile.fileType && targetFile.fileType.includes('uns'))
  }, [fileParseType, targetFile.fileType]);

  // 3. 状态管理（增加与ParagraphEdit一致的定位状态）
  const [postion, setPostion] = useState([1, 0])
  const [labelsMap, setLabelsMap] = useState(new Map())
  const labelsMapRef = useRef(new Map())
  const labelsMapTempRef = useRef({})
  const [labelChange, setLabelChange] = useState(false)
  const [showPos, setShowPos] = useState(false)
  const labelTextRef = useRef<any>(partitions);
  const [rePostion, setRePostion] = useState(false)

  // 4. 初始化标签数据（完全对齐ParagraphEdit的initData逻辑）
  useEffect(() => {
    if (selectedChunkIndex === -1) return
    setLabelChange(false);
    // 仅对非uns类型的非PDF文件清空标签
    if (suffix !== 'pdf' && !isUnsType) {
      setSelectedBbox([]);
      labelsMapRef.current = new Map();
      setRePostion(!rePostion);
      return setLabelsMap(new Map());
    }
    let setPostioned = false;
    const labelsMap = new Map();

    // 优先使用缓存的标签数据
    const cachedLabels = labelsMapTempRef.current[selectedChunkIndex];
    if (cachedLabels) {
      setRePostion(!rePostion);
      setLabelsMap(cachedLabels);
      labelsMapRef.current = cachedLabels;
      return;
    }

    // 转换标签数据（与ParagraphEdit使用相同方法）
    const allLabels = convertJsonData(labelTextRef.current || partitions);
    const activeIds = new Set();

    // 标记当前chunk的激活标签
    chunks?.forEach(chunk => {
      if (chunk.chunkIndex === selectedChunkIndex) {
        const bboxes = (chunk.bbox && JSON.parse(chunk.bbox).chunk_bboxes) || [];
        bboxes.forEach(label => {
          const id = [label.page, ...label.bbox].join('-');
          activeIds.add(id);
          // 初始定位到第一个激活标签
          if (!setPostioned) {
            setPostion([label.page, label.bbox[1]]);
            setPostioned = true;
          }
        });
      }
    });

    // 设置标签激活状态
    allLabels.forEach((label) => {
      labelsMap.set(label.id, {
        ...label,
        active: activeIds.has(label.id)
      });
    });

    if (labelsMap.size) {
      setRePostion(!rePostion);
      setLabelsMap(labelsMap);
      labelsMapRef.current = labelsMap;
    }
  }, [suffix, chunks, selectedChunkIndex, isUnsType, partitions]);
  useEffect(() => {
    // 当 chunks 变化且存在选中的 chunkIndex 时，检查该 chunk 是否仍存在
    if (selectedChunkIndex !== -1) {
      const chunkExists = chunks.some(c => c.chunkIndex === selectedChunkIndex);
      if (!chunkExists) {
        // 清除该 chunk 对应的标签
        setLabelsMap(new Map());
        labelsMapRef.current = new Map();
        delete labelsMapTempRef.current[selectedChunkIndex];
        setSelectedBbox([]);
      }
    }
  }, [chunks, selectedChunkIndex, setLabelsMap, setSelectedBbox]);
  // 5. 页面滚动和定位逻辑（对齐ParagraphEdit的postion计算）
  useEffect(() => {
    setPostion(prev => [prev[0], prev[1] + selectedChunkDistanceFactor]);
  }, [selectedChunkDistanceFactor]);

  // 计算定位位置（与ParagraphEdit一致）
  const calculatedPostion = useMemo(() => {
    const labelsArray = Array.from(labelsMap.values());
    const target = labelsArray.find(el => el.active);
    return target ? [target.page, postion[1]] : [0, 0];
  }, [rePostion, postion]);

  // 6. 页面标签分组（与ParagraphEdit的labels计算一致）
  const pageLabels = useMemo(() => {
    return Array.from(labelsMap.values()).reduce((acc, item) => {
      if (!acc[item.page]) acc[item.page] = [];
      acc[item.page].push({ ...item });
      return acc;
    }, {});
  }, [labelsMap]);

  // 7. 标签选择逻辑（完全对齐ParagraphEdit的handleSelectLabels
  const handleSelectLabels = (lbs) => {
    if (selectedChunkIndex === -1) return;

    const distinct = {};
    const newActiveLabelMap = lbs.reduce((map, { id, active }) => {
      const partId = labelTextRef.current[id]?.part_id;
      if (distinct[partId]) return map;

      distinct[partId] = true;
      // 同步相同part_id的标签状态
      Object.keys(labelTextRef.current).forEach(key => {
        if (labelTextRef.current[key]?.part_id === partId) {
          map.set(key, active);
        }
      });
      return map;
    }, new Map());

    // 更新标签状态
    const newMap = new Map(labelsMap);
    const bbox = [];

    Array.from(labelsMap.values()).forEach(item => {
      const value = newActiveLabelMap.get(item.id);
      if (value !== undefined) {
        newMap.set(item.id, { ...item, active: value });
        if (value) bbox.push({ page: item.page, bbox: item.label });
      } else if (item.active) {
        bbox.push({ page: item.page, bbox: item.label });
      }
    });

    setSelectedBbox(bbox);
    labelsMapRef.current = newMap;
    setLabelsMap(newMap);
    setLabelChange(true);
  };

  // 8. 页面滚动检测（新增，与ParagraphEdit的handlePageChange一致）
  const handlePageChange = (offset, h, paperSize, scale) => {
    if (offset === 0) return;
    const labelsArray = Array.from(labelsMap.values());
    setShowPos(!labelsArray.some(item => {
      const pageHeight = (item.page - 1) * paperSize;
      const labelTop = pageHeight + item.label[1] / scale;
      return item.active && labelTop > offset && labelTop < (offset + h);
    }));
  };

  // 9. 渲染逻辑（统一与ParagraphEdit的fileView逻辑）
  const render = () => {
    const { url, load } = urlState;

    // 加载状态处理
    if (!load && !url) return <div className="flex justify-center items-center h-full text-gray-400">预览失败</div>;
    if (!url) return <div className="flex justify-center items-center h-full text-gray-400"><LoadingIcon /></div>;

    // 新版文件预览
    switch (suffix) {
      case 'ppt':
      case 'pptx': return <div className="flex justify-center items-center h-full text-gray-400">
        <div className="text-center">
          <img
            className="size-52 block"
            src={__APP_ENV__.BASE_URL + "/assets/knowledge/damage.svg"} alt="" />
          <p>此文件类型不支持预览</p>
        </div>
      </div>
      case 'pdf':
        return (
          <FileView
            startIndex={0}
            select={selectedChunkIndex !== -1}
            fileUrl={url}
            labels={pageLabels}
            scrollTo={calculatedPostion}
            onSelectLabel={handleSelectLabels}
            onPageChange={handlePageChange}
          />
        );
      case 'txt': return <TxtFileViewer filePath={url} />;
      case 'md': return <TxtFileViewer markdown filePath={url} />;
      case 'html': return <TxtFileViewer html filePath={url} />;
      case 'doc':
      case 'docx': return <DocxPreview filePath={previewUrl || url} />;
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'bmp': return (
        <img
          className="border"
          src={url.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL)}
          alt="预览图片"
        />
      );
      case 'xlsx':
      case 'xls':
      case 'csv':
        return (
          <div>
            <ExcelPreview filePath={previewUrl || url} />
          </div>
        )
      default:
        return <div className="flex justify-center items-center h-full text-gray-400">
          <div className="text-center">
          </div>
        </div>;
    }
  };

  // 10. 覆盖分段逻辑（完全对齐ParagraphEdit）
  const handleOvergap = () => {
    setLabelChange(false);
    let prevType = '';
    let prevPartId = '';
    let str = '';

    Array.from(labelsMap.values()).forEach((item) => {
      if (typeof labelTextRef.current[item.id] === 'string') {
        return alert('文件已失效，请上传新文件后重试');
      }

      if (item.active) {
        const { text, type, part_id } = labelTextRef.current[item.id];

        if (str === '') {
          str += text + (type === 'Title' ? '\n' : '');
        } else {
          if (prevPartId === part_id) {
            str += text;
          } else if (prevType === 'Table' || type === 'Table' || (type === 'Title' && prevType !== type)) {
            str += '\n\n' + text;
          } else {
            str += '\n' + text;
          }
        }

        prevType = type;
        prevPartId = part_id;
      }
    });

    setNeedCoverData({ index: selectedChunkIndex, txt: str });
    labelsMapTempRef.current[selectedChunkIndex] = labelsMap;
  };

  useEffect(() => {
    return () => {
      setNeedCoverData({ index: -1, txt: '' });
    }
  }, [])



  return <div className={cn('relative', step === 3 ? "w-full max-w-[50%]" : "w-1/2", step === 2 ? "-mt-9 w-full max-w-[50%]" : "")} onClick={e => {
    e.stopPropagation()
  }}>
    <div className={`${edit ? 'absolute -top-8 right-0 z-10' : 'relative'} flex justify-center items-center mb-2 text-sm h-10`}>
      <div className={`${labelChange ? '' : 'hidden'} flex items-center`}>
        <Info className='mr-1 text-red-500' size={14} />
        <span className="text-red-500">{t('segmentRangeDetected')}</span>
        <span className="text-primary cursor-pointer" onClick={handleOvergap}>{t('overwriteSegment')}</span>
      </div>
    </div>
    <div className={`relative ${['csv', 'xlsx', 'xls'].includes(file.suffix) ? '' : "overflow-y-auto"}  ${edit ? 'h-[calc(100vh-206px)]' : 'h-[calc(100vh-284px)]'}`}>
      {render(file.suffix)}
    </div>
  </div>
};
