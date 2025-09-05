import { FileIcon } from "@/components/bs-icons/file";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue
} from "@/components/bs-ui/select";
import { delChunkInPreviewApi, getFilePathApi, previewFileSplitApi, updatePreviewChunkApi } from "@/controllers/API";
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
    showPreview: boolean;
    onPreviewResult?: (isSuccess: boolean) => void;
}
export type Partition = {
    [key in string]: { text: string, type: string, part_id: string }
}
export default function PreviewResult({ previewCount, rules, step, applyEachCell, resultFiles, cellGeneralConfig, showPreview, originalSplitRule, onPreviewResult, kId }: IProps) {
    console.log(kId, resultFiles,step, 33);

    const { id } = useParams()
    const [previewSuccess, setPreviewSuccess] = useState(true);
    const [chunks, setChunks] = useState([]) // 当前文件分块
    const [partitions, setPartitions] = useState<Partition>({}) // 当前文件分区
   const [selectId, setSelectId] = useState(step === 1 ||step ===2? resultFiles[0]?.id : ''); // 当前选择文件id
    const [syncChunksSelectId, setSelectIdSyncChunks] = useState(''); // 当前选择文件id(与chunk更新保持同步)
const currentStepRef = useRef(step);

useEffect(() => {
    if (currentStepRef.current !== step) {
        currentStepRef.current = step;
        let file
        if (step === 3) {
            file = rules.fileList[0]
            console.log(file.id, 22);
            setSelectId(file.id)
        }
        if (step === 1 && resultFiles.length > 0) {
            setSelectId(resultFiles[0].id);
        }
    }
}, [step, rules.fileList, resultFiles]);
    const currentFile = useMemo(() => {  // 当前选择文件
        console.log(rules, 1);
        let _currentFile
        if (step === 2) {
            _currentFile = rules.fileList.find(file => file.id === selectId)
        } else {
            _currentFile = resultFiles[0];
        }

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
    const [fileViewUrl, setFileViewUrl] = useState({ load: true, url: '' }) // 当前选择文件预览url

    const [loading, setLoading] = useState(false)
    const prevPreviewCountMapRef = useRef({})
    useEffect(() => {
        console.log(!selectId,12);
        
      console.log(resultFiles, 333);

        const fetchPreviewData = async () => {
            setTimeout(() => {
                setLoading(true)
            }, 0);
            setFileViewUrl({ load: true, url: '' })
            setChunks([])

            // 合并配置
            const { fileList, pageHeaderFooter, chunkOverlap, chunkSize, enableFormula, forceOcr, knowledgeId, retainImages, separator, separatorRule } = rules
            let _currentFile
        if (step === 2) {
            _currentFile = rules.fileList.find(file => file.id === selectId)
        } else {
            _currentFile = resultFiles[0].id
        }

            try {
           
                let filePathRes
                // 先获取文件路径
                if (step === 1 || (step === 2 && !showPreview)) {
                    console.log(selectId, originalSplitRule, '分段');
                    if(selectId){
                         filePathRes = await getFilePathApi(selectId);
                    }else{
                         filePathRes = await getFilePathApi(_currentFile);
                    }
                   
                }else {
                    filePathRes=resultFiles[0].file_path
                }
                const configSource = (step === 1 || (step === 2 && !showPreview))
                    ? originalSplitRule
                    : {
                        separator,
                        separator_rule: separatorRule,
                        chunk_size: chunkSize,
                        chunk_overlap: chunkOverlap,
                        retain_images: retainImages,
                        enable_formula: enableFormula,
                        force_ocr: forceOcr,
                        filter_page_header_footer: pageHeaderFooter
                    };
                console.log( filePathRes , currentFile, 12);

                captureAndAlertRequestErrorHoc(previewFileSplitApi({
                    // 使用配置源的所有值
                    cache: prevPreviewCountMapRef.current[currentFile?.id] === previewCount,
                    knowledge_id: id || kId,
                    file_list: [{
                        file_path: filePathRes || currentFile?.filePath,
                        excel_rule: (step === 1 || (step === 2 && !showPreview))
                            ? originalSplitRule?.excel_rule
                            : (applyEachCell ? currentFile?.excelRule : { ...cellGeneralConfig })
                    }],
                    separator: configSource.separator,
                    separator_rule: configSource.separator_rule,
                    chunk_size: configSource.chunk_size,
                    chunk_overlap: configSource.chunk_overlap,
                    retain_images: configSource.retain_images,
                    enable_formula: configSource.enable_formula,
                    force_ocr: configSource.force_ocr,
                    fileter_page_header_footer: configSource.filter_page_header_footer
                }), err => {
                    // 解析失败时,使用支持的原文件预览
                    ["pdf", "txt", "md", "html", "docx", "png", "jpg", "jpeg", "bmp"].includes(currentFile.suffix)
                        && setFileViewUrl({ load: false, url: currentFile.filePath })
                    setPreviewSuccess(false);
                    onPreviewResult && onPreviewResult(false);
                }).then(res => {
                    if (!res) {
                        setFileViewUrl({ load: false, url: '' })
                        setPreviewSuccess(false);
                        onPreviewResult && onPreviewResult(false);
                        return setLoading(false)
                    }
                    if (res === 'canceled') return
                    console.log("previewFileSplitApi:", res)
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
                    const success = res.chunks && res.chunks.length > 0;
                    setPreviewSuccess(success);
                    onPreviewResult && onPreviewResult(success);
                    setLoading(false)
                })
            } catch (error) {
                console.error('Failed to get file path:', error);
                setLoading(false);
                setPreviewSuccess(false);
                onPreviewResult && onPreviewResult(false);
            }

            prevPreviewCountMapRef.current[currentFile.id] = previewCount
        }

        fetchPreviewData();
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
        const bbox = { chunk_bboxes: selectedBbox }
        updatePreviewChunkApi({
            knowledge_id: Number(id), file_path: currentFile.filePath, chunk_index: chunkIndex, text, bbox: JSON.stringify(bbox)
        })
        setChunks(chunks => chunks.map(chunk => chunk.chunkIndex === chunkIndex ? { ...chunk, text } : chunk))
    }

    return (<div className={cn("h-full flex gap-2 justify-center", step === 2 ? 'w-[100%]' : 'w-full')}>
        {console.log(chunks, partitions, 212, fileViewUrl)}
        {(step === 3 || (step === 2 && !previewCount)) && currentFile && <PreviewFile
            urlState={fileViewUrl}
            file={currentFile}
            chunks={chunks}
            setChunks={setChunks}
            partitions={partitions}
        />}
        <div className={cn('relative', 'w-[100%]')}>
            {/* 下拉框 - 右上角 */}
            <div className="flex justify-end">
                <Select value={selectId} onValueChange={setSelectId}>
                    <SelectTrigger className="w-72">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {console.log(step,89)}
                        {step === 2 && rules.fileList.map((file, index) => (
                            <SelectItem key={file.id} value={file.id}>
                                <div className="flex items-center gap-2">
                                    <FileIcon type={file.suffix} className="size-4 min-w-4" />
                                    {file.fileName}
                                </div>
                            </SelectItem>
                        ))}
                          {step === 1 &&
                            <SelectItem key={resultFiles[0].id} value={resultFiles[0].id}>
                                <div className="flex items-center gap-2">
                                    <FileIcon type={resultFiles[0].suffix} className="size-4 min-w-4" />
                                    {resultFiles[0].fileName}
                                </div>
                            </SelectItem>
                        }
                    </SelectContent>
                </Select>
            </div>

            {/* 其他内容 */}
            <PreviewParagraph
                fileId={syncChunksSelectId}
                fileSuffix={currentFile?.suffix}
                previewCount={previewCount}
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
