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
}
export type Partition = {
    [key in string]: { text: string, type: string, part_id: string }
}
export default function PreviewResult({ previewCount, rules, step, applyEachCell, cellGeneralConfig }: IProps) {
    const { id } = useParams()

    const [chunks, setChunks] = useState([]) // 当前文件分块
    const [partitions, setPartitions] = useState<Partition>({}) // 当前文件分区
    const [selectId, setSelectId] = useState(''); // 当前选择文件id
    const [syncChunksSelectId, setSelectIdSyncChunks] = useState(''); // 当前选择文件id(与chunk更新保持同步)
    useEffect(() => {
        const file = rules.fileList[0]
        setSelectId(file.id)
    }, [])
    const currentFile = useMemo(() => {  // 当前选择文件
        return rules.fileList.find(file => file.id === selectId)
    }, [selectId, rules])

    const [loading, setLoading] = useState(false)
    const prevPreviewCountRef = useRef(0)
    useEffect(() => {
        if (!selectId) return
        setLoading(true)
        // 合并配置
        const { fileList, pageHeaderFooter, chunkOverlap, chunkSize, enableFormula, forceOcr, knowledgeId
            , retainImages, separator, separatorRule } = rules
        const currentFile = fileList.find(file => file.id === selectId)
        captureAndAlertRequestErrorHoc(previewFileSplitApi({
            // 缓存(修改规则后需要清空缓存, 切换文件使用缓存)
            // previewCount变更时为重新预览分段操作,不使用缓存
            cache: prevPreviewCountRef.current === previewCount,
            knowledge_id: id,
            file_list: [{
                file_path: currentFile?.filePath,
                excel_rule: applyEachCell
                    ? currentFile.excelRule
                    : { ...cellGeneralConfig }
            }],
            separator,
            separator_rule: separatorRule,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
            retain_images: retainImages,
            enable_formula: enableFormula,
            force_ocr: forceOcr,
            fileter_page_header_footer: pageHeaderFooter

        })).then(res => {
            console.log("previewFileSplitApi:", res)
            res && setChunks(res.chunks.map(chunk => ({
                bbox: chunk.metadata.bbox,
                chunkIndex: chunk.metadata.chunk_index,
                page: chunk.metadata.page,
                text: chunk.text
            })))
            setSelectIdSyncChunks(selectId)

            setPartitions(res.partitions)
            setLoading(false)
        })

        prevPreviewCountRef.current = previewCount
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

    return (<div className={cn("h-full flex gap-2 justify-center", step === 2 ? 'w-1/2' : 'w-full')}>
        {step === 3 && currentFile && < PreviewFile
            file={currentFile}
            chunks={chunks}
            partitions={partitions}
        />}
        <div className={cn('relative', step === 2 ? 'w-full' : 'w-1/2')}>
            {/* 下拉框 - 右上角 */}
            <div className="flex justify-end">
                <Select value={selectId} onValueChange={setSelectId}>
                    <SelectTrigger className="w-72">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {rules.fileList.map((file, index) => (
                            <SelectItem key={file.id} value={file.id}>
                                <div className="flex items-center gap-2">
                                    <FileIcon type={file.suffix} className="size-4" />
                                    {file.fileName}
                                </div>
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>

            {/* 其他内容 */}
            <PreviewParagraph
                fileId={syncChunksSelectId}
                fileSuffix={currentFile?.suffix}
                edit={step === 3}
                loading={loading}
                chunks={chunks}
                onDel={handleDelete}
                onChange={handleChunkChange}
            />
        </div>
    </div>
    )
}
