import { Dialog, DialogContent } from "@/components/bs-ui/dialog";
import SelectSearch from "@/components/bs-ui/select/select";
import { delChunkInPreviewApi, previewFileSplitApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Info } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import ParagraphEdit from "./ParagraphEdit";
import { ParagraphsItem } from "./Paragraphs";
import { LoadingIcon } from "@/components/bs-icons/loading";

const FileUploadParagraphs = forwardRef(function ({ open = false, change, onChange }: any, ref) {
    const { id } = useParams()
    const { t } = useTranslation()
    const paramsRef = useRef<any>(null)
    const [loading, setLoading] = useState(false)
    const [paragraph, setParagraph] = useState<any>({
        fileId: '',
        chunkId: '',
        show: false
    })

    const [fileValue, setFileValue] = useState('')
    const fileValueRef = useRef('')
    const allFilesRef = useRef([])
    const [files, setFiles] = useState([])

    const fileCachesRef = useRef({})

    useEffect(() => {
        if (!open) {
            fileValueRef.current = ''
            fileCachesRef.current = {}
        }
    }, [open])

    useImperativeHandle(ref, () => ({
        load(data, files) {
            paramsRef.current = data
            fileCachesRef.current = {}

            allFilesRef.current = files.map(el => ({
                label: el.name,
                value: el.path
            }))
            setFiles([...allFilesRef.current])
            loadchunks(fileValueRef.current || files[0].path) // default first 
        }
    }))

    const [paragraphs, setParagraphs] = useState<any>([])
    const [previewFileUrl, setFileUrl] = useState('')
    const [isUns, setIsUns] = useState(false)
    const [partitions, setPartitions] = useState<any>([])
    // 加载文件分段结果
    const loadchunks = async (fileValue) => {
        if (!fileValue) return
        setLoading(true)
        setFileValue(fileValue)
        fileValueRef.current = fileValue
        previewFileSplitApi({ ...paramsRef.current, file_path: fileValue, cache: !!fileCachesRef.current[fileValue] }).then(res => {
            setLoading(false)
            setParagraphs(res.chunks)
            // setFileUrl(fileValue)
            setFileUrl(res.file_url)
            setIsUns(res.parse_type === 'uns')
            setPartitions(res.partitions)

            fileCachesRef.current[fileValue] = true // chace tag
        })
    }

    const handleSelectSearch = (e: any) => {
        const value = e.target.value
        if (!value) return setFiles([...allFilesRef.current])
        // 按label查找
        const res = allFilesRef.current.filter(el => el.label.indexOf(value) !== -1 || el.value === fileValue)
        setFiles(res)
    }

    const handleReload = () => {
        setLoading(true)
        onChange(false)
        fileCachesRef.current = {}

        // loadchunks(fileValue)
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
            <LoadingIcon />
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
                    loadchunks(val)
                }}>
            </SelectSearch>
            <div className={`${change ? '' : 'hidden'} flex items-center`}>
                <Info className='mr-1 text-red-500' />
                <span className="text-red-500">{t('policyChangeDetected', { ns: 'knowledge' })}</span>
                <span className="text-primary cursor-pointer" onClick={handleReload}>{t('regeneratePreview', { ns: 'knowledge' })}</span>
            </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 min-w-[770px]">
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
                    oriFilePath={fileValue}
                    filePath={previewFileUrl}
                    fileId={paragraph.fileId}
                    chunkId={paragraph.chunkId}
                    onClose={() => setParagraph({ ...paragraph, show: false })}
                    onChange={(val) => setParagraphs(paragraphs.map(item =>
                        item.metadata.chunk_index === paragraph.chunkId ? { ...item, text: val } : item))
                    }
                />
            </DialogContent>
        </Dialog>
    </div>
});

export default FileUploadParagraphs