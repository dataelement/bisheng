import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import StepProgress from "@/components/bs-ui/step";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronLeft } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";
import FileUploadStep4 from "./components/FileUploadStep4";

const StepLabels = [
    '上传文件',
    '分段策略',
    '原文对比',
    '数据处理'
]

export default function FilesUpload() {
    const { t } = useTranslation('knowledge')
    const navigate = useNavigate();
    const { message } = useToast()

    const [currentStep, setCurrentStep] = useState(1)
    // 文件列表
    const [resultFiles, setResultFiles] = useState([])
    const [isSubmitting, setIsSubmitting] = useState(false);
    
    const _tempConfigRef = useRef({})
    // 保存知识库
    const submittingRef = useRef(false);
    const handleSave = (_config) => {
        // 如果正在提交，直接返回
        if (submittingRef.current) { return; }
        // 加锁
        submittingRef.current = true;
        setIsSubmitting(true);
        captureAndAlertRequestErrorHoc(subUploadLibFile(_config).then(res => {
            const _repeatFiles = res.filter(e => e.status === 3)

            if (_repeatFiles.length) {
                setRepeatFiles(_repeatFiles)
                repeatCallBackRef.current = () => setCurrentStep(4)
                // TODO 移动到第一步?
                // } else if (failFiles.length) {
                //     bsConfirm({
                //         desc: <div>
                //             <p>{t('fileUploadResult', { total: fileCount, failed: failFiles.length })}</p>
                //             <div className="max-h-[160px] overflow-y-auto no-scrollbar">
                //                 {failFiles.map(el => <p className=" text-red-400" key={el.id}>{el.name}</p>)}
                //             </div>
                //         </div>,
                //         onOk(next) {
                //             next()
                //             setCurrentStep(4)
                //         }
                //     })
            } else {
                message({ variant: 'success', description: t('addSuccess') })
                setCurrentStep(4)
            }

            // 设置fileId
            setResultFiles(files => files.map((file, index) => ({
                ...file,
                fileId: res[index].id
            })
            ))
        }).finally(() => {
            // 无论成功失败都要解锁
            submittingRef.current = false;
            setIsSubmitting(false);
        }))

        _tempConfigRef.current = _config
    }

    // 默认配置保存
    const handleSaveByDefaultConfig = async (_config) => {
        await captureAndAlertRequestErrorHoc(subUploadLibFile(_config).then(res => {
            const _repeatFiles = res.filter(e => e.status === 3)
            if (_repeatFiles.length) {
                setRepeatFiles(_repeatFiles)
                repeatCallBackRef.current = () => navigate(-1)
            } else {
                message({ variant: 'success', description: "添加成功" })
                navigate(-1)
            }
        }))
    }

    // 重复文件列表
    const [repeatFiles, setRepeatFiles] = useState([])
    const repeatCallBackRef = useRef(() => {
        setCurrentStep(4)
    })
    // 重试解析
    const [retryLoad, setRetryLoad] = useState(false)
    const handleRetry = (objs) => {
        setRetryLoad(true)
        const params = {
            knowledge_id: Number(_tempConfigRef.current.knoledge_id),
            separator: _tempConfigRef.current.separator,
            separator_rule: _tempConfigRef.current.separator_rule,
            chunk_size: _tempConfigRef.current.chunk_size,
            chunk_overlap: _tempConfigRef.current.chunk_overlap,
            file_objs: objs
        }
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi(params).then(res => {
            setRepeatFiles([])
            setRetryLoad(false)
            // onNext()
            message({ variant: 'success', description: t('addSuccess') });
            repeatCallBackRef.current()
        }))
    }

    return <div className="relative h-full flex flex-col">
        <div className="pt-4 px-4">
            {/* back */}
            <div className="flex items-center">
                <Button
                    variant="outline"
                    size="icon"
                    className="bg-[#fff] size-8"
                    onClick={() => navigate(-1)}
                >
                    <ChevronLeft />
                </Button>
                <span className="text-foreground text-sm font-black pl-4">返回知识库</span>
            </div>
            {/* 上方步进条 */}
            <StepProgress
                align="center"
                currentStep={currentStep}
                labels={StepLabels}
            />
        </div>

        {/* 主要内容区域*/}
        <div className="flex flex-1 overflow-hidden px-4"> {/* pb-16为底部按钮留空间 */}
            <div className="w-full overflow-y-auto">
                <div className="h-full">

                    <FileUploadStep1
                        hidden={currentStep !== 1}
                        onNext={(files) => {
                            setResultFiles(files);
                            setCurrentStep(2);
                        }}
                        onSave={handleSaveByDefaultConfig}
                    />

                    <FileUploadStep2
                        step={currentStep}
                        resultFiles={resultFiles}
                        isSubmitting={isSubmitting}
                        onNext={(step, _config) => {
                            step === 3 ? setCurrentStep(step) : handleSave(_config)
                        }}
                        onPrev={() => setCurrentStep(currentStep - 1)}
                    />
                    {currentStep === 4 && <FileUploadStep4 data={resultFiles} />}
                </div>
            </div>
        </div>

        {/* 重复文件提醒 */}
        <Dialog open={!!repeatFiles.length} onOpenChange={b => !b && setRepeatFiles([])}>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>{t('modalTitle')}</DialogTitle>
                    <DialogDescription>{t('modalMessage')}</DialogDescription>
                </DialogHeader>
                <ul className="overflow-y-auto max-h-[400px]">
                    {repeatFiles.map(el => (
                        <li key={el.id} className="py-2 text-red-500">{el.remark}</li>
                    ))}
                </ul>
                <DialogFooter>
                    <Button className="h-8" variant="outline" onClick={() => { setRepeatFiles([]); repeatCallBackRef.current() }}>{t('keepOriginal')}</Button>
                    <Button className="h-8" disabled={retryLoad} onClick={() => handleRetry(repeatFiles)}>
                        {retryLoad && <span className="loading loading-spinner loading-xs"></span>}{t('override')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    </div>
};
