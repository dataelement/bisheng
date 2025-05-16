import StepProgress from "@/components/bs-ui/step";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft } from "lucide-react";
import { useRef, useState } from "react";
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
    const [stepEnd, setStepEnd] = useState(false)

    const [change, setChange] = useState(false)

    const [showView, setShowView] = useState(false)
    const viewRef = useRef(null)
    const handlePreviewClick = (data, files) => {
        setChange(false)
        setShowView(true)
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

    return <div className="flex px-2 py-4 h-full gap-2">
        {/* 文件上传 */}
        <div className="w-full min-w-[520px]">
            {/* head back */}
            <div className="flex items-center">
                <ShadTooltip content={t('back')} side="top">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => navigate(-1)}  >
                        <ArrowLeft className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                <span className=" text-foreground text-sm font-black pl-4">{t('back')}</span>
            </div>
            <StepProgress currentStep={currentStep} align="center" labels={StepLabels} />
            {/* step component */}
            <div className="h-[calc(100vh-190px)] relative">
                <FileUploadStep1 hidden={currentStep !== 1}
                    onNext={(files) => {
                        setResultFiles(files)
                        setCurrentStep(2)
                    }}
                    onSave={(files) => {
                        setResultFiles(files)
                        handleSave(files)
                    }} />
                {stepEnd && (
                    <FileUploadStep2
                        fileInfo={fileInfo}
                        onPrev={() => setStepEnd(false)}
                        onPreview={handlePreviewClick}
                        onChange={() => setChange(true)}
                    />
                )}
            </div>
        </div>
    </div>
};
