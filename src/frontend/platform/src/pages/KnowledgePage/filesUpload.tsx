import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import StepProgress from "@/components/bs-ui/step";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { retryKnowledgeFileApi, subUploadLibFile } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ChevronLeft } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";
import FileUploadStep4 from "./components/FileUploadStep4";
import PreviewResult from "./components/PreviewResult";

const StepLabels = [
    '上传文件',
    '分段策略',
    '原文对比',
    '数据处理'
]

export default function FilesUpload() {
    const { t } = useTranslation('knowledge')
    const navigate = useNavigate();
    const location = useLocation();
    const { id } = useParams();
    const { message } = useToast()
    const [isAdjustMode, setIsAdjustMode] = useState(location.state?.isAdjustMode || false);
    const [currentStep, setCurrentStep] = useState(1);
    
    // 文件列表
    const [resultFiles, setResultFiles] = useState(() => {
        if (location.state?.isAdjustMode && location.state?.fileData) {
            const fileData = location.state.fileData;
            return [{
                id: fileData.id,
                fileName: fileData.name,
                file_path: fileData.filePath,
                suffix: fileData.suffix,
                fileType: fileData.fileType === 'table' ? 'table' : 'file'
            }];
        }
        return [];
    });
    
    // 新增：存储分段策略配置
    const [segmentRules, setSegmentRules] = useState(null);
    
    const [isSubmitting, setIsSubmitting] = useState(false);
    const adjustedStepLabels = isAdjustMode 
        ? ['分段策略', '原文对比', '数据处理'] 
        : ['上传文件', '分段策略', '原文对比', '数据处理'];
    
    const _tempConfigRef = useRef({})
    
    // 保存知识库
    const submittingRef = useRef(false);
    const handleSave = (_config) => {
        if (submittingRef.current) return;
        submittingRef.current = true;
        setIsSubmitting(true);
        
        captureAndAlertRequestErrorHoc(subUploadLibFile(_config).then(res => {
            const _repeatFiles = res.filter(e => e.status === 3)

            if (_repeatFiles.length) {
                setRepeatFiles(_repeatFiles)
                repeatCallBackRef.current = () => setCurrentStep(isAdjustMode ? 3 : 4)
            } else {
                message({ variant: 'success', description: t('addSuccess') })
                setCurrentStep(isAdjustMode ? 3 : 4)
            }

            // 设置fileId
            setResultFiles(files => files.map((file, index) => ({
                ...file,
                fileId: res[index].id
            })))
        }).finally(() => {
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
        setCurrentStep(isAdjustMode ? 3 : 4)
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
            message({ variant: 'success', description: t('addSuccess') });
            repeatCallBackRef.current()
        }))
    }
    
    const handleBack = () => {
        if (currentStep === 1) {
            navigate(-1); 
        } else {
            setCurrentStep(prev => prev - 1);
        }
    };

    // 处理从 FileUploadStep2 接收的分段策略配置
    const handleStep2Next = (step, config) => {
        if (config) {
            // 保存分段策略配置
            setSegmentRules(config);
        }
        setCurrentStep(step);
    };

    return (
        <div className="relative h-full flex flex-col">
            <div className="pt-4 px-4">
                {/* back */}
                <div className="flex items-center">
                    <Button
                        variant="outline"
                        size="icon"
                        className="bg-[#fff] size-8"
                        onClick={handleBack}
                    >
                        <ChevronLeft />
                    </Button>
                    <span className="text-foreground text-sm font-black pl-4">返回知识库</span>
                </div>
                
                {/* 上方步进条 */}
                <StepProgress
                    align="center"
                    currentStep={isAdjustMode  ? currentStep - 1 : currentStep}
                    labels={adjustedStepLabels}
                />
            </div>

            {/* 主要内容区域 */}
            <div className="flex flex-1 overflow-hidden px-4">
                <div className="w-full overflow-y-auto">
                    <div className="h-full">
                        {/* 步骤1: 文件上传 (仅正常模式) */}
                        {!isAdjustMode && (
                            <FileUploadStep1
                                onNext={(files) => {
                                    setResultFiles(files);
                                    setCurrentStep(2);
                                }}
                                onSave={handleSaveByDefaultConfig}
                                hidden={currentStep !== 1}
                            />
                        )}
                        
                        {/* 步骤2: 分段策略 (正常模式) / 步骤1: 分段策略 (调整模式) */}
                        {(currentStep === (isAdjustMode ? 1 : 2)) && (
                            <FileUploadStep2
                                step={currentStep}
                                resultFiles={resultFiles}
                                isSubmitting={isSubmitting}
                                onNext={handleStep2Next}
                                onPrev={handleBack}
                                isAdjustMode={isAdjustMode}
                            />
                        )}

                        {/* 步骤3: 原文对比 (正常模式) / 步骤2: 原文对比 (调整模式) */}
                        {(currentStep === (isAdjustMode ? 2 : 3)) && segmentRules && (
                            <PreviewResult
                                rules={segmentRules.rules} 
                                resultFiles={resultFiles} // 如果需要文件信息也可以传递
                                onPrev={() => setCurrentStep(isAdjustMode ? 1 : 2)}
                                onNext={(config) => {
                                    // 下一步进入数据处理并保存
                                    const nextStep = isAdjustMode ? 3 : 4;
                                    setCurrentStep(nextStep);
                                    handleSave(config);
                                }}
                            />
                        )}

                        {/* 步骤4: 数据处理 (正常模式) / 步骤3: 数据处理 (调整模式) */}
                        {currentStep === (isAdjustMode ? 3 : 4) && <FileUploadStep4 data={resultFiles} />}
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
                        <Button className="h-8" variant="outline" onClick={() => { setRepeatFiles([]); repeatCallBackRef.current() }}>
                            {t('keepOriginal')}
                        </Button>
                        <Button className="h-8" disabled={retryLoad} onClick={() => handleRetry(repeatFiles)}>
                            {retryLoad && <span className="loading loading-spinner loading-xs"></span>}
                            {t('override')}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}