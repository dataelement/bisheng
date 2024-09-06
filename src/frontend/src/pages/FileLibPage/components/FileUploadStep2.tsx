import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { t } from "i18next";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import FileUploadSplitStrategy from "./FileUploadSplitStrategy";
import { LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

const initialStrategies = [
    { id: '1', regex: '\\n\\n', position: 'after' },
    { id: '2', regex: '\\n', position: 'after' }
];

interface IProps {
    fileInfo: { fileCount: number, files: any, failFiles: any }
    onPrev: () => void
    onPreview: (data: any, files: any) => void
    onChange: () => void
}

export default function FileUploadStep2({ fileInfo, onPrev, onPreview, onChange }: IProps) {
    const { id: kid } = useParams()

    const chunkType = useRef('smart')
    // 切分
    const [strategies, setStrategies] = useState(initialStrategies);
    // size
    const [size, setSize] = useState('1000')
    // 符号
    const [overlap, setOverlap] = useState('100')
    useEffect(() => {
        onChange()
    }, [strategies, size, overlap])

    const [loading, setLoading] = useState(false)
    const { message } = useToast()
    const navaigate = useNavigate()

    const getParams = (size, overlap) => {
        const [separator, separator_rule] = strategies.reduce((res, item) => {
            const { regex, position } = item
            res[0].push(regex)
            res[1].push(position)
            return res
        }, [[], []])
        const handleFileParams = chunkType.current === 'chunk' ? {
            separator,
            separator_rule,
            chunk_size: size,
            chunk_overlap: overlap
        } : {}
        return {
            knowledge_id: Number(kid),
            ...handleFileParams
        }
    }
    const handleSubmit = async () => {
        const { fileCount, failFiles } = fileInfo
        const params = {
            ...getParams(size, overlap),
            file_list: fileInfo.files.map(file => ({ file_path: file.path }))
        }

        setLoading(true)
        await captureAndAlertRequestErrorHoc(subUploadLibFile(params).then(res => {
            const _repeatFiles = res.filter(e => e.status === 3)
            if (_repeatFiles.length) {
                setRepeatFiles(_repeatFiles)
            } else {
                failFiles.length ? bsConfirm({
                    desc: <div>
                        <p>{t('lib.fileUploadResult', { total: fileCount, failed: failFiles.length })}</p>
                        <div className="max-h-[160px] overflow-y-auto no-scrollbar">
                            {failFiles.map(el => <p className=" text-red-400" key={el.id}>{el.name}</p>)}
                        </div>
                    </div>,
                    onOk(next) {
                        next()
                        navaigate(-1)
                    }
                }) : (message({ variant: 'success', description: '添加成功' }), navaigate(-1))
            }
        }))
        setLoading(false)
    }

    // 重复文件列表
    const [repeatFiles, setRepeatFiles] = useState([])
    // 重试解析
    const [retryLoad, setRetryLoad] = useState(false)
    const handleRetry = (objs) => {
        setRetryLoad(true)
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(objs).then(res => {
            setRepeatFiles([])
            setRetryLoad(false)
            // onNext()
        }))
    }

    // 预览
    const handlePreview = () => {
        const params = getParams(size, overlap)
        onPreview(params, fileInfo.files)
    }

    return <div className="flex flex-col">
        <div className="flex items-center gap-2 my-6 px-12 text-sm font-bold max-w-96">
            <span>①上传文件</span>
            <div className="h-[1px] flex-grow bg-gray-300"></div>
            <span className="text-primary">②文档处理策略</span>
        </div>
        <Tabs defaultValue="smart" className="w-full mt-4 text-center" onValueChange={(val) => chunkType.current = val}>
            <TabsList className="a mx-auto">
                <TabsTrigger value="smart" className="roundedrounded-xl">默认策略</TabsTrigger>
                <TabsTrigger value="chunk">自定义策略</TabsTrigger>
            </TabsList>
            <TabsContent value="smart">
            </TabsContent>
            <TabsContent value="chunk">
                <div className="grid items-start gap-4 mt-8 max-w-[760px] mx-auto" style={{ gridTemplateColumns: '114px 1fr' }}>
                    <Label htmlFor="name" className="mt-2.5 flex justify-end text-left">切分方式 <QuestionTooltip content={'可选择下方筛选项，或通过正则表达式自定义切分规则，例如在"第.{1,3}条" 前进行切分时，会在“第1条”、“第ab条”“第三条”等文本之前进行切分。'} /></Label>
                    <FileUploadSplitStrategy data={strategies} onChange={setStrategies} />
                    <Label htmlFor="name" className="mt-2.5 text-right">{t('code.splitLength')}</Label>
                    <Input id="name" type="number" value={size} onChange={(e) => setSize(e.target.value)} placeholder={t('code.splitSizePlaceholder')} />
                    <Label htmlFor="name" className="mt-2.5 text-right">{t('code.chunkOverlap')}</Label>
                    <Input id="name" value={overlap} onChange={(e) => setOverlap(e.target.value)} placeholder={t('code.chunkOverlap')} />
                </div>
            </TabsContent>
        </Tabs>
        <div className="flex justify-end mt-8 gap-4">
            <Button className="h-8" variant="outline" onClick={onPrev}>上一步</Button>
            <Button disabled={loading} className="h-8" onClick={handleSubmit}>{loading && <LoadIcon />} 提交</Button>
            <Button className="h-8" onClick={handlePreview}>预览分段结果</Button>
        </div>

        {/* 重复文件提醒 */}
        <Dialog open={!!repeatFiles.length} onOpenChange={b => !b && setRepeatFiles([])}>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>{t('lib.modalTitle')}</DialogTitle>
                    <DialogDescription>{t('lib.modalMessage')}</DialogDescription>
                </DialogHeader>
                <ul className="overflow-y-auto max-h-[400px]">
                    {repeatFiles.map(el => (
                        <li key={el.id} className="py-2 text-red-500">{el.remark}</li>
                    ))}
                </ul>
                <DialogFooter>
                    <Button className="h-8" variant="outline" onClick={() => { setRepeatFiles([]); navaigate(-1) }}>{t('lib.keepOriginal')}</Button>
                    <Button className="h-8" disabled={retryLoad} onClick={() => handleRetry(repeatFiles)}>
                        {retryLoad && <span className="loading loading-spinner loading-xs"></span>}{t('lib.override')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    </div>
};
