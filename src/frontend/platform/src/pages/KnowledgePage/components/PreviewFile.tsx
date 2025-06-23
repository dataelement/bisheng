import FileView from "@/components/bs-comp/FileView";
import { Info } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useKnowledgeStore from "../useKnowledgeStore";
import DocxPreview from "./DocxFileViewer";
import { Partition } from "./PreviewResult";
import TxtFileViewer from "./TxtFileViewer";

/**
 * 
 * chunks -> labelsMap
 * labelsMap -> pageLabels -> ui
 * 选中label -> 更新labelsMap
 * 覆盖chunk -> labelsMap + partitions = string -> store -> update markdown
 */
export default function PreviewFile({ urlState, file, partitions, chunks, setChunks }
    : { urlState: { load: false, url: '' }, file: any, partitions: Partition, chunks: any, setChunks: any }) {
    const { t } = useTranslation('knowledge')
    const selectedChunkIndex = useKnowledgeStore((state) => state.selectedChunkIndex);
    const selectedChunkDistanceFactor = useKnowledgeStore((state) => state.selectedChunkDistanceFactor);
    const setNeedCoverData = useKnowledgeStore((state) => state.setNeedCoverData);
    const setSelectedBbox = useKnowledgeStore((state) => state.setSelectedBbox);
    // test
    // partitions = {
    //     '1-40-40-400-80': { text: '1111', type: 'Title', part_id: '1' },
    //     '1-140-140-400-180': { text: '2222', type: 'Title', part_id: '1' },
    //     '1-240-240-400-330': { text: '3333', type: 'Title', part_id: '2' }
    // }

    const [postion, setPostion] = useState([1, 0])
    const [labelsMap, setLabelsMap] = useState(new Map()) // {p-bbox: label}
    const labelsMapRef = useRef(new Map())

    const labelsMapTempRef = useRef({}) // 临时存每个分段覆盖后的labels结果
    // 分段标注有变更
    const [labelChange, setLabelChange] = useState(false)
    useEffect(() => {
        setLabelChange(false)
        if (file.suffix !== 'pdf') {
            setSelectedBbox([])
            labelsMapRef.current = new Map()
            return setLabelsMap(new Map())
        }

        let setPostioned = false;
        const labelsMap = new Map();

        const _labelsMap = labelsMapTempRef.current[selectedChunkIndex]
        if (labelsMapTempRef.current[selectedChunkIndex]) {
            setLabelsMap(_labelsMap)
            labelsMapRef.current = _labelsMap
            return
        }

        // 合并覆盖的activeLabels
        // const activeLabels = chunks.reduce((res, chunk) => {
        //     res = {...res, ...chunk.activeLabels}
        //     return res
        // }, {})
        // if (chunks[0]) chunks[0].bbox = [{ page: 1, bbox: [40, 40, 400, 80] }, { page: 1, bbox: [140, 140, 400, 180] }]
        // if (chunks[1]) chunks[1].bbox = [{ page: 1, bbox: [240, 240, 400, 330] }]
        chunks.forEach(chunk => {
            const bboxes = (chunk.bbox && JSON.parse(chunk.bbox).chunk_bboxes) || [];
            const isActive = chunk.chunkIndex === selectedChunkIndex;

            bboxes.forEach(label => {
                const id = [label.page, ...label.bbox].join('-');
                const existing = labelsMap.get(id);

                // const activeded = chunk.activeLabels?.[id];
                // if (activeded !== undefined) {
                //     labelsMap.set(id, {
                //         id,
                //         page: label.page,
                //         label: label.bbox,
                //         active: activeded,
                //         txt: chunk.text
                //     });
                // } else
                if (isActive || !existing) {
                    // 处理标签优先级：当前标签激活时强制覆盖，非激活时保留已有（可能包含激活状态）
                    labelsMap.set(id, {
                        id,
                        page: label.page,
                        label: label.bbox,
                        // active: obj?.active !== false && isActive,
                        active: isActive,
                        txt: chunk.text
                    });
                }


                // 初始定位到第一个激活的标签
                if (isActive && !setPostioned) {
                    setPostion([label.page, label.bbox[1]]) // 增量
                    setPostioned = true;
                }
            });
        });
        labelsMap.size && setLabelsMap(labelsMap)
        labelsMapRef.current = labelsMap
    }, [file.suffix, chunks, selectedChunkIndex]);

    useEffect(() => {
        labelsMapTempRef.current = {}
    }, [file])

    // 点击定位
    useEffect(() => {
        setPostion((p) => [p[0], p[1] + selectedChunkDistanceFactor])
    }, [selectedChunkDistanceFactor])

    const pageLabels = useMemo(() => {
        // 转换为按页面分组的对象
        return Array.from(labelsMap.values()).reduce((acc, item) => {
            (acc[item.page] ||= []).push(item);
            return acc;
        }, {});
    }, [labelsMap])

    // 选择标注框
    const handleSelectLabels = (lbs) => {
        if (selectedChunkIndex === -1) return

        const distinct = {}
        const activeLabels = lbs.reduce((label, { id, active }) => {
            const partId = partitions[id].part_id
            if (distinct[partId]) return label // same partId
            distinct[partId] = true
            // 相同的partId同时被选中
            Object.keys(partitions).forEach((key) => {
                if (partitions[key].part_id === partId) {
                    label.push({ id: key, active })
                }
            })
            return label
        }, [])

        // 高亮(active)标注
        const newMap = new Map(labelsMap); // 浅拷贝原 Map
        const bbox = []
        activeLabels.forEach((item) => {
            // 记录当前chunk选中的bbox

            const label = newMap.get(item.id);
            if (label) {
                newMap.set(item.id, { ...label, active: item.active });
                bbox.push({ page: label.page, bbox: label.label })
            }
        });
        // 记录当前chunk选中的bbox
        setSelectedBbox(bbox)

        labelsMapRef.current = newMap
        setLabelsMap(newMap);
        setLabelChange(true)
    }

    const render = (type) => {
        const { url, load } = urlState

        if (!load && !url) return <div className="flex justify-center items-center h-full text-gray-400">预览失败</div>
        if (!url) return <div className="flex justify-center items-center h-full text-gray-400">加载中...</div>
        switch (type) {
            case 'ppt':
            case 'pptx':
            case 'pdf':
                return <FileView
                    startIndex={0}
                    select={false} // selectedChunkIndex !== -1}
                    fileUrl={url}
                    labels={pageLabels}
                    scrollTo={postion}
                    onSelectLabel={handleSelectLabels}
                // onPageChange={handlePageChange}
                />
            case 'txt': return <TxtFileViewer filePath={url} />
            case 'md': return <TxtFileViewer markdown filePath={url} />
            case 'html': return <TxtFileViewer html filePath={url} />
            case 'doc':
            case 'docx': return <DocxPreview filePath={url} />
            case 'png':
            case 'jpg':
            case 'jpeg':
            case 'bmp': return <img
                className="border"
                src={url.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL)} alt="" />
            default:
                return <div className="flex justify-center items-center h-full text-gray-400">预览失败</div>
        }
    }

    // 覆盖分段
    const handleOvergap = (params) => {
        setLabelChange(false)
        let prevType = ''
        let prevPartId = ''
        let str = ''
        const activeMap = {}
        // 标注块拼接段落
        labelsMap.forEach((item, key) => {
            if (item.active) {
                activeMap[item.id] = true

                const { text, type, part_id } = partitions[item.id]
                if (str === '') {
                    // 第一个块, title类型，末尾加单换行
                    str += text + (type === 'Title' ? '\n' : '')
                } else {
                    // 非第一个块
                    if (prevPartId === part_id) {
                        // 上一个和当前是同一段落
                        str += text
                    } else if (prevType === 'Table' || type === 'Table' || (type === 'Title' && prevType !== type)) {
                        // 上一个是表格 or 当前是表格 or 当前是title并上一个不是title
                        str += '\n\n' + text
                    } else {
                        str += '\n' + text
                    }
                }

                prevType = type
                prevPartId = part_id
            } else {
                activeMap[item.id] = false
            }
        })
        console.log('JSON. :>> ', JSON.stringify(str));
        setNeedCoverData({ index: selectedChunkIndex, txt: str })
        // setChunks(chunks => chunks.map(chunk => chunk.chunkIndex === selectedChunkIndex ? { ...chunk, activeLabels: activeMap } : chunk))
        labelsMapTempRef.current[selectedChunkIndex] = labelsMap
    }

    if (['xlsx', 'xls', 'csv'].includes(file.suffix)) return null


    return <div className="w-1/2" onClick={e => {
        e.stopPropagation()
    }}>
        <div className="flex justify-center items-center relative h-10 mb-2 text-sm">
            <div className={`${labelChange ? '' : 'hidden'} flex items-center`}>
                <Info className='mr-1 text-red-500' size={14} />
                <span className="text-red-500">{t('segmentRangeDetected')}</span>
                <span className="text-primary cursor-pointer" onClick={handleOvergap}>{t('overwriteSegment')}</span>
            </div>
        </div>
        <div className="relative h-[calc(100vh-284px)] overflow-y-auto">
            {render(file.suffix)}
        </div>
    </div>
};
