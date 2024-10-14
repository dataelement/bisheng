import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import {
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle
} from "@/components/bs-ui/card"
import { Dialog, DialogContent } from "@/components/bs-ui/dialog"
import { SearchInput } from "@/components/bs-ui/input"
import AutoPagination from "@/components/bs-ui/pagination/autoPagination"
import MultiSelect from "@/components/bs-ui/select/multi"
import { delChunkApi, getKnowledgeChunkApi, readFileByLibDatabase } from "@/controllers/API"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useTable } from "@/util/hook"
import { FileText } from "lucide-react"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { useParams } from "react-router-dom"
import ParagraphEdit from "./ParagraphEdit"
import { LoadingIcon } from "@/components/bs-icons/loading"

export const ParagraphsItem = ({ data, disabled = false, onEdit, onDeled }) => {
    const { t } = useTranslation('knowledge')
    const handleDel = () => {
        bsConfirm({
            desc: t('confirmDeleteSegment'),
            onOk: () => {
                onDeled(data)
            }
        })
    }

    return (
        <Card className="relative w-[378px]">
            {/* 序号部分 */}
            <div className="absolute right-4 top-4 font-semibold">#{data.metadata.chunk_index + 1}</div>
            <CardHeader>
                <CardTitle className="font-semibold pr-10 leading-6">{data.metadata.source || ""}</CardTitle>
            </CardHeader>
            <CardContent className="pb-2">
                <p className="truncate-multiline text-sm text-muted-foreground h-[60px]">
                    {data.text}
                </p>
            </CardContent>
            <CardFooter className="flex justify-between items-center">
                <div className="flex space-x-2">
                    <Button variant="link" disabled={disabled} className="p-0" onClick={handleDel}>
                        {t('delete')}
                    </Button>
                    <Button variant="link" disabled={disabled} className="p-0" onClick={onEdit}>
                        {t('edit')}
                    </Button>
                </div>
                <p className="text-xs text-muted-foreground">{t('charCount', { count: data.text.length })}</p>
            </CardFooter>
        </Card>
    );
};


export default function Paragraphs({ fileId }) {
    const { t } = useTranslation('knowledge')
    const { id } = useParams()
    const [value, setValue] = useState([])
    useEffect(() => {
        if (fileId) {
            setValue([fileId])
            filterData({ file_ids: [fileId] })
        }
    }, [fileId])

    const [files, setFiles] = useState<any>([])
    useEffect(() => {
        readFileByLibDatabase({ id, page: 1, pageSize: 4000, status: 2 }).then(res => {
            setFiles(res.data.map(el => ({ label: el.file_name, value: el.id })))
        })
    }, [])

    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData, refreshData } = useTable({}, (param) =>
        getKnowledgeChunkApi({ ...param, limit: param.pageSize, knowledge_id: id }).then(res => {
            return res
        })
    )

    const handleDeleteChunk = (data) => {
        captureAndAlertRequestErrorHoc(delChunkApi({
            knowledge_id: id,
            file_id: data.metadata.file_id,
            chunk_index: data.metadata.chunk_index
        }))
        reload()
    }

    const [paragraph, setParagraph] = useState<any>({
        fileId: '',
        chunkId: '',
        isUns: false,
        show: false
    })

    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="absolute right-0 top-[-62px] flex gap-4 items-center">
            <SearchInput placeholder={t('searchSegments')} onChange={(e) => search(e.target.value)}></SearchInput>
            <div className="min-w-72 max-w-[400px]">
                <MultiSelect
                    close
                    className="max-w-[630px]"
                    multiple
                    scroll
                    value={value}
                    options={files}
                    placeholder={t('selectFile')}
                    searchPlaceholder=''
                    onChange={(ids) => filterData({ file_ids: ids })}
                ></MultiSelect>
            </div>
        </div>
        <div className="h-[calc(100vh-144px)] overflow-y-auto pb-20 bg-background-main">
            <div className="flex flex-wrap gap-2 p-2 items-start">
                {
                    datalist.length ? datalist.map((item, index) => (
                        <ParagraphsItem
                            key={index}
                            data={item}
                            onEdit={() => setParagraph({
                                fileId: item.metadata.file_id,
                                chunkId: item.metadata.chunk_index,
                                isUns: item.parse_type === 'uns',
                                show: true
                            })}
                            onDeled={handleDeleteChunk}
                        ></ParagraphsItem>
                    )) :
                        <div className="flex justify-center items-center flex-col size-full text-gray-400">
                            <FileText width={160} height={160} className="text-border" />
                            {t('uploadPrompt')}
                        </div>
                }
            </div>
        </div>
        <div className="bisheng-table-footer px-6">
            <p></p>
            <div>
                <AutoPagination
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
        <Dialog open={paragraph.show} onOpenChange={(show) => setParagraph({ ...paragraph, show })}>
            <DialogContent close={false} className='size-full max-w-full sm:rounded-none p-0 border-none'>
                <ParagraphEdit
                    fileId={paragraph.fileId}
                    chunkId={paragraph.chunkId}
                    isUns={paragraph.isUns}
                    onClose={() => setParagraph({ ...paragraph, show: false })}
                    onChange={(value) => refreshData((item) => item.metadata.chunk_index === paragraph.chunkId, { text: value })}
                />
            </DialogContent>
        </Dialog>
    </div>
};
