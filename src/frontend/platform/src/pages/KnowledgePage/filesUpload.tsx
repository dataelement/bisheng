import StepProgress from "@/components/bs-ui/step";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft, ChevronLeft, FileText } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";
import { Button } from "@/components/bs-ui/button";

const StepLabels = [
    '上传文件',
    '分段策略',
    '原文对比',
    '数据处理'
]

export default function FilesUpload() {
    const { t } = useTranslation('knowledge')
    const navigate = useNavigate();
    const [stepEnd, setStepEnd] = useState(false)

    const [change, setChange] = useState(false)

    const [showView, setShowView] = useState(false)
    const viewRef = useRef(null)
    const handlePreviewClick = (data, files) => {
        setChange(false)
        setShowView(true)
        console.log('5678', files);

        viewRef.current.load(data, files)
    }

    const [fileInfo, setFileInfo] = useState(null)

    ///// new
    const [currentStep, setCurrentStep] = useState(1)
    const [resultFiles, setResultFiles] = useState([])
    console.log('resultFiles :>> ', resultFiles);
    // 策略配置
    const [config, setConfig] = useState(null)

    const handleSave = (_files) => {
        const files = resultFiles || _files
        console.log(' todo resultFiles :>> ', files);
    }
    const [showSecondDiv, setShowSecondDiv] = useState(false);
    return <div className="relative h-full flex flex-col">
        {/* 固定在上方的进度条 */}
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
            <StepProgress
                currentStep={currentStep}
                align="center"
                labels={StepLabels}
                className="mt-4"
            />
        </div>

        {/* 主要内容区域 - 使用flex布局分成两部分 */}
        <div className="flex flex-1 overflow-hidden px-4 pb-16"> {/* pb-16为底部按钮留空间 */}
            {/* 左侧文件上传区域 */}
            <div className="w-full overflow-y-auto">
                <div className="h-full">

                    <FileUploadStep1 hidden={currentStep !== 1}
                        onNext={(files) => {
                            setFileInfo(files);
                            setResultFiles(files);
                            setCurrentStep(2);
                        }}
                        onSave={(files) => {
                            setResultFiles(files);
                            handleSave(files);
                        }}
                    />

                    {currentStep === 2 && (
                        <FileUploadStep2
                            resultFiles={resultFiles}
                            fileInfo={fileInfo}
                            setShowSecondDiv={setShowSecondDiv}
                            onPrev={() => setStepEnd(false)}
                            onPreview={handlePreviewClick}
                            onChange={() => setChange(true)}
                        />
                    )}
                    {currentStep === 3 && <div>1111</div>}
                </div>
            </div>
        </div>

        {/* 固定在右下角的按钮 */}
        {currentStep === 2 && (
            <div className="fixed bottom-4 right-8 flex gap-4 bg-white p-2 rounded-lg shadow-sm">
                <Button
                    className="h-8"
                    variant="outline"
                    onClick={() => setCurrentStep(currentStep - 1)}
                >
                    {t('previousStep')}
                </Button>
                <Button
                    className="h-8"
                    onClick={() => setCurrentStep(currentStep + 1)}
                >
                    {t('nextStep')}
                </Button>
            </div>
        )}
    </div>
};
