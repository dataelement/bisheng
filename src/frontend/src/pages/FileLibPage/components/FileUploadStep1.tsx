
import { LoadIcon } from "@/components/bs-icons";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import Upload from "@/components/bs-ui/upload";
import { locationContext } from "@/contexts/locationContext";
import { retryKnowledgeFileApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useContext, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function FileUploadStep1({ onNext }) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    const uploadRef = useRef<any>(null)
    const { message } = useToast()
    // 重复文件列表
    const [repeatFiles, setRepeatFiles] = useState([])

    const [fileCount, setFileCount] = useState(0)
    const [loading, setLoading] = useState(false)
    const handleSaveFiles = () => {
        const [fileCount, sucessFileCount, failFileNames] = uploadRef.current?.getUploadResult()
        if (!sucessFileCount) return message({ variant: 'error', description: t('code.selectFileToUpload') })
        setLoading(true)
        // api
        const _repeatFiles = [].filter(e => e.status === 3)
        if (_repeatFiles.length) {
            setRepeatFiles(_repeatFiles)
        } else {
            failFileNames.length && bsConfirm({
                desc: <div>
                    <p>{t('lib.fileUploadResult', { total: fileCount, failed: failFileNames.length })}</p>
                    <div className="max-h-[160px] overflow-y-auto no-scrollbar">
                        {failFileNames.map(str => <p className=" text-red-400" key={str}>{str}</p>)}
                    </div>
                </div>,
                onOk(next) {
                    next()
                    onNext()
                }
            })
        }
        setLoading(false)
        onNext()
    }

    // 重试解析
    const [retryLoad, setRetryLoad] = useState(false)
    const handleRetry = (objs) => {
        setRetryLoad(true)
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(objs).then(res => {
            setRepeatFiles([])
            setRetryLoad(false)
            onNext()
        }))
    }

    return <div className="flex flex-col">
        <div className="flex items-center gap-2 my-6 px-12">
            <span className="text-primary">①上传文件</span>
            <div className="h-[1px] flex-grow bg-gray-300"></div>
            <span>②文档处理策略</span>
        </div>
        <Upload ref={uploadRef} url='/api/v1/knowledge/upload' accept={appConfig.libAccepts} progressClassName='max-h-[374px]' onFileCountChange={setFileCount} />
        <div className="flex justify-end">
            <Button className="px-10 mt-4" disabled={loading || !fileCount} onClick={handleSaveFiles}>
                {loading && <LoadIcon className="mr-2" />} {fileCount ? <span>{fileCount}<span className="mx-1">|</span></span> : null}下一步
            </Button>
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
                    <Button className="h-8" variant="outline" onClick={() => setRepeatFiles([])}>{t('lib.keepOriginal')}</Button>
                    <Button className="h-8" disabled={retryLoad} onClick={() => handleRetry(repeatFiles)}>
                        {retryLoad && <span className="loading loading-spinner loading-xs"></span>}{t('lib.override')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    </div>
};
