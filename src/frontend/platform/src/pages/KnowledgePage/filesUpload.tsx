import { Button } from "@/components/bs-ui/button";
import StepProgress from "@/components/bs-ui/step";
import { ChevronLeft } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";

const StepLabels = [
    '上传文件',
    '分段策略',
    '原文对比',
    '数据处理'
]

export default function FilesUpload() {
    const { t } = useTranslation('knowledge')
    const navigate = useNavigate();

    const [currentStep, setCurrentStep] = useState(1)
    const [resultFiles, setResultFiles] = useState([])
    console.log('resultFiles :>> ', resultFiles);
    // 策略配置
    const [config, setConfig] = useState(null)
    // 直接保存
    const handleFinishUpload = (_files) => {
        const files = resultFiles || _files
        console.log(' todo resultFiles :>> ', files);
        // TODO: 保存后返回上一页
    }

    return <div className="relative h-full flex flex-col">
        <div className="pt-4 px-4">
            <div className="flex items-center">
                <Button
                    variant="outline"
                    size="icon"
                    className="bg-[#fff] size-8"
                    onClick={() => navigate(-1)}
                >
                    <ChevronLeft />
                </Button>
                <span className="text-foreground text-sm font-black pl-4">{t('back')}</span>
            </div>
            {/* 固定在上方的步进条 */}
            <StepProgress
                align="center"
                currentStep={currentStep}
                labels={StepLabels}
            />
        </div>

        {/* 主要内容区域*/}
        <div className="flex flex-1 overflow-hidden px-4 pb-16"> {/* pb-16为底部按钮留空间 */}
            <div className="w-full overflow-y-auto">
                <div className="h-full">

                    <FileUploadStep1
                        hidden={currentStep !== 1}
                        onNext={(files) => {
                            setResultFiles(files);
                            setCurrentStep(2);
                        }}
                        onSave={(files) => {
                            setResultFiles(files);
                            handleFinishUpload(files);
                        }}
                    />

                    {[2, 3].includes(currentStep) && <FileUploadStep2
                        setCurrentStep={setCurrentStep}
                        step={currentStep}
                        resultFiles={resultFiles}
                        onNext={(_config) => {
                            setConfig(_config);
                            setCurrentStep(4);
                        }}
                    />}
                    {currentStep === 4 && <div>数据处理</div>}
                </div>
            </div>
        </div>
    </div>
};
