import { FileIcon } from "@/components/bs-icons/file";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue
} from "@/components/bs-ui/select";
import { delChunkInPreviewApi, previewFileSplitApi, updatePreviewChunkApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { cn } from "@/util/utils";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import useKnowledgeStore from "../useKnowledgeStore";
import PreviewFile from "./PreviewFile";
import PreviewParagraph from "./PreviewParagraph";

interface IProps {
    rules: any;
    step: number;
    /** 刷新 */
    previewCount: number;
    applyEachCell: boolean;
    cellGeneralConfig: any;
    handlePreviewResult: (isSuccess: boolean) => void;
    kId?: string | number;
    showPreview?: boolean;
}
export type Partition = {
    [key in string]: { text: string, type: string, part_id: string }
}
export default function PreviewResult({ showPreview, previewCount, rules, step, applyEachCell, cellGeneralConfig, kId, handlePreviewResult }: IProps) {
    const { fileId: id } = useParams()
console.log(showPreview, previewCount, rules, step, applyEachCell, cellGeneralConfig, kId,handlePreviewResult,676786);

    const [chunks, setChunks] = useState([]) // 当前文件分块
    const [partitions, setPartitions] = useState<Partition>(null) // 当前文件分区
    const [selectId, setSelectId] = useState(''); // 当前选择文件id
    const [syncChunksSelectId, setSelectIdSyncChunks] = useState(''); // 当前选择文件id(与chunk更新保持同步)
    useEffect(() => {
        const file = rules.fileList[0]
        setSelectId(file.id)
    }, [])
    const currentFile = useMemo(() => {  // 当前选择文件
        const _currentFile = rules.fileList.find(file => file.id === selectId)
        // 触发keydown事件,切换tab
        if (_currentFile) {
            const dom = document.getElementById(_currentFile.fileType === 'table' ? 'knowledge_table_tab' : 'knowledge_file_tab')
            const keydownEvent = new KeyboardEvent('keydown', {
                key: 'Enter',
                code: 'Enter',
                keyCode: 13,
                which: 13,
                bubbles: true,
                cancelable: true
            });
            dom && dom.dispatchEvent(keydownEvent);
        }
        return _currentFile
    }, [selectId, rules])
    const [fileViewUrl, setFileViewUrl] = useState<{ load: boolean; url: string }>({ load: true, url: '' }) // 当前选择文件预览url

    const [loading, setLoading] = useState(false)
    const prevPreviewCountMapRef = useRef({})
    useEffect(() => {
        if (!selectId) return
        setTimeout(() => {
            setLoading(true)
        }, 0);
        setFileViewUrl({ load: true, url: '' })
        setChunks([])
        // 合并配置
        const { fileList, pageHeaderFooter, chunkOverlap, chunkSize, enableFormula, forceOcr, knowledgeId
            , retainImages, separator, separatorRule } = rules
        const currentFile = fileList.find(file => file.id === selectId)

        let preview_url
        console.log(currentFile,789);
        
        if (showPreview) {
            preview_url = currentFile.previewUrl || currentFile?.filePath
        } else {
            preview_url = currentFile?.filePath
        }

        // 将 UI 可见的 "\\n" 还原为真实 "\n"
        const normalizeSeparators = (arr) => (arr || []).map((s) =>
            typeof s === 'string' ? s.replace(/\\n/g, '\n') : s
        );

        captureAndAlertRequestErrorHoc(previewFileSplitApi({
            // 缓存(修改规则后需要清空缓存, 切换文件使用缓存)
            // previewCount变更时为重新预览分段操作,不使用缓存
            cache: prevPreviewCountMapRef.current[currentFile.id] === previewCount,
            knowledge_id: id || kId,
            file_list: [{
                file_path: preview_url,
                excel_rule: applyEachCell
                    ? currentFile.excelRule
                    : { ...cellGeneralConfig }
            }],
            separator: normalizeSeparators(separator),
            separator_rule: separatorRule,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
            retain_images: retainImages,
            enable_formula: enableFormula,
            force_ocr: forceOcr,
            fileter_page_header_footer: pageHeaderFooter

        }), err => {
            // 解析失败时,使用支持的原文件预览
            ["pdf", "txt", "md", "html", "docx", "png", "jpg", "jpeg", "bmp"].includes(currentFile.suffix)
                && setFileViewUrl({ load: false, url: currentFile.filePath })
        }).then(res => {

            if (!res) {
                handlePreviewResult(false);
                setFileViewUrl({ load: false, url: '' })
                return setLoading(false)
            }
            if (res === 'canceled') return
            console.log("previewFileSplitApi:", res)
            handlePreviewResult(true);
            res && setChunks(res.chunks.map(chunk => ({
                bbox: chunk.metadata.bbox,
                activeLabels: {},
                chunkIndex: chunk.metadata.chunk_index,
                page: chunk.metadata.page,
                text: chunk.text
            })))
            setSelectIdSyncChunks(selectId)
            setFileViewUrl({ load: false, url: res.file_url })
            setPartitions(res.partitions)
            setLoading(false)
        })

        prevPreviewCountMapRef.current[currentFile.id] = previewCount
    }, [selectId, previewCount])

    const handleDelete = async (chunkIndex: number, text: string) => {
        await captureAndAlertRequestErrorHoc(delChunkInPreviewApi({
            knowledge_id: id,
            file_path: rules.fileList.find(file => file.id === selectId)?.filePath,
            text: text,
            chunk_index: chunkIndex
        }))
        const res = chunks.filter(chunk => chunk.chunkIndex !== chunkIndex)
        setChunks(res)
    }

    // 更新分段
    const selectedBbox = useKnowledgeStore((state) => state.selectedBbox);
    const handleChunkChange = (chunkIndex, text) => {
       
        
         const existingBbox = chunks[chunkIndex]?.bbox ? JSON.parse(chunks[chunkIndex].bbox) : { chunk_bboxes: [] };
          const targetChunkBboxes = selectedBbox && selectedBbox.length > 0 
        ? selectedBbox 
        : existingBbox.chunk_bboxes;
    const bbox = { 
        chunk_bboxes: targetChunkBboxes 
    };
    console.log( bbox,existingBbox,98999898);
    
        updatePreviewChunkApi({
            knowledge_id: Number(id)||kId, file_path: currentFile.filePath, chunk_index: chunkIndex, text, bbox: JSON.stringify(bbox)
        })
        setChunks(chunks => chunks.map(chunk => chunk.chunkIndex === chunkIndex ? { ...chunk, text } : chunk))
    }

    return (<div className={cn("h-full flex gap-2 justify-center", "w-full")}>
        
        {(step === 3 || step === 2 && !previewCount) && currentFile && !loading  && <PreviewFile
            urlState={fileViewUrl}
            file={currentFile}
            step={step}
            chunks={chunks}
            setChunks={setChunks}
            partitions={partitions}
        />}
         <div className={cn('relative',  "w-full")}>
            {/* 下拉框 - 右上角 */}
            {(step === 3 || (step === 2 && showPreview)) && (
                <div className="flex justify-end">
                    <Select value={selectId} onValueChange={setSelectId}>
                        <SelectTrigger className="w-72">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {rules.fileList.map((file, index) => (
                                <SelectItem key={file.id} value={file.id}>
                                    <div className="flex items-center gap-2">
                                        <FileIcon type={file.suffix} className="size-4 min-w-4" />
                                        {file.fileName}
                                    </div>
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>)
            }
            {/* 其他内容 */}
            <PreviewParagraph
                fileId={syncChunksSelectId}
                fileSuffix={currentFile?.suffix}
                previewCount={previewCount}
                className="h-[calc(100vh-284px)]"
                edit={step === 3 || step === 2}
                loading={loading}
                chunks={chunks}
                onDel={handleDelete}
                onChange={handleChunkChange}
            />
        </div>
    </div>
    )
}