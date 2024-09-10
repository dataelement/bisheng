import { Dialog, DialogContent } from "@/components/bs-ui/dialog";
import SelectSearch from "@/components/bs-ui/select/select";
import { delChunkInPreviewApi, previewFileSplitApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { InfoCircledIcon } from "@radix-ui/react-icons";
import isEqual from "lodash-es/isEqual";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import ParagraphEdit from "./ParagraphEdit";
import { ParagraphsItem } from "./Paragraphs";

const FileUploadParagraphs = forwardRef(function ({ open = false, change, onChange }: any, ref) {
    const { id } = useParams()
    const paramsRef = useRef<any>(null)
    const [loading, setLoading] = useState(false)
    const [paragraph, setParagraph] = useState<any>({
        fileId: '',
        chunkId: '',
        show: false
    })

    const [fileValue, setFileValue] = useState('')
    const allFilesRef = useRef([])
    const [files, setFiles] = useState([])

    const paramChangRef = useRef(false)
    const preveParamsRef = useRef(null)
    useImperativeHandle(ref, () => ({
        load(data, files) {
            paramsRef.current = data
            // has change
            if (!paramChangRef.current || !isEqual(data, preveParamsRef.current)) {
                paramChangRef.current = false
                preveParamsRef.current = data
            }

            allFilesRef.current = files.map(el => ({
                label: el.name,
                value: el.path
            }))
            setFiles([...allFilesRef.current])
            loadchunks(files[0].path) // default first 
        }
    }))


    const [paragraphs, setParagraphs] = useState<any>([])
    const [fileUrl, setFileUrl] = useState('')
    const [isUns, setIsUns] = useState(false)
    const [partitions, setPartitions] = useState<any>([])
    // 加载文件分段结果
    const loadchunks = async (fileValue) => {
        if (!fileValue) return
        setLoading(true)
        setFileValue(fileValue)
        previewFileSplitApi({ ...paramsRef.current, file_path: fileValue, cache: paramChangRef.current }).then(res => {
            setLoading(false)
            setParagraphs(res.chunks)
            setFileUrl(res.file_url)
            setIsUns(res.parse_type === 'uns')
            setPartitions(res.partitions)
        })
    }

    const handleSelectSearch = (value: any) => {
        // 按label查找
        const res = allFilesRef.current.filter(el => el.label.indexOf(value) !== -1)
        setFiles(res)
    }

    const handleReload = () => {
        setLoading(true)
        onChange(false)

        loadchunks(fileValue)
    }

    const handleDeleteChunk = async (data) => {
        await captureAndAlertRequestErrorHoc(delChunkInPreviewApi({
            knowledge_id: id,
            file_path: fileValue,
            text: data.text,
            chunk_index: data.metadata.chunk_index
        }))
        const res = paragraphs.filter(el => el.metadata.chunk_index !== data.metadata.chunk_index)
        setParagraphs(res)
    }

    if (!open) return null

    if (loading) return (
        <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <span className="loading loading-infinity loading-lg"></span>
        </div>
    )

    return <div className="h-full overflow-y-auto p-2">
        <div className="flex gap-2">
            <SelectSearch value={fileValue} options={files}
                selectPlaceholder=''
                inputPlaceholder=''
                selectClass="w-64"
                onChange={handleSelectSearch}
                onValueChange={(val) => {
                    paramChangRef.current = true
                    loadchunks(val)
                }}>
            </SelectSearch>
            <div className={`${change ? '' : 'hidden'} flex items-center`}>
                <InfoCircledIcon className='mr-1 text-red-500' />
                <span className="text-red-500">检测到策略调整，</span>
                <span className="text-primary cursor-pointer" onClick={handleReload}>重新生成预览</span>
            </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
            {
                paragraphs.map(item => (
                    <ParagraphsItem
                        key={item.text}
                        disabled={change}
                        data={item}
                        onDeled={handleDeleteChunk}
                        onEdit={() => {
                            setParagraph({
                                fileId: item.metadata.file_id,
                                chunkId: item.metadata.chunk_index,
                                show: true
                            })
                        }} />
                ))
            }
        </div>
        <Dialog open={paragraph.show} onOpenChange={(show) => setParagraph({ ...paragraph, show })}>
            <DialogContent close={false} className='size-full max-w-full sm:rounded-none p-0 border-none'>
                <ParagraphEdit
                    chunks={paragraphs}
                    partitions={partitions}
                    isUns={isUns}
                    filePath={fileUrl}
                    fileId={paragraph.fileId}
                    chunkId={paragraph.chunkId}
                    onClose={() => setParagraph({ ...paragraph, show: false })}
                />
            </DialogContent>
        </Dialog>
    </div>
});

export default FileUploadParagraphs