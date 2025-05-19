import StepProgress from "@/components/bs-ui/step";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft, ChevronLeft, FileText } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";
import { Button } from "@/components/bs-ui/button";
import FileUploadParagraphs from "./components/FileUploadParagraphs";

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
        console.log('5678',files);
        
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
    return <div className="flex px-2 py-4 h-full gap-2 w-full">
        {/* 文件上传 */}
        <div className={showSecondDiv ? "w-1/2 min-w-[520px]" : "w-full"}>
            <div className="flex items-center">
                {/* <ShadTooltip content={t('back')} side="top">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => navigate(-1)}  >
                        <ArrowLeft className="side-bar-button-size" />
                    </button>
                </ShadTooltip> */}
                <Button variant="outline" size="icon" className={ 'bg-[#fff] size-8'}
                    onClick={() => navigate(-1)}
                ><ChevronLeft /></Button>
                <span className=" text-foreground text-sm font-black pl-4">{t('back')}</span>
            </div>
            <StepProgress currentStep={currentStep} align="center" labels={StepLabels} />
            {/* step component */}
            <div className="h-[calc(100vh-190px)] relative">
                <FileUploadStep1 hidden={currentStep !== 1}
                    onNext={(files) => {
                        setFileInfo(files)
                        setCurrentStep(2)
                    }}
                    onSave={(files) => {
                        setResultFiles(files)
                        handleSave(files)
                    }} />
                {currentStep === 2 && (
                    <FileUploadStep2
                    fileInfo={fileInfo}
                    setShowSecondDiv={setShowSecondDiv}
                    onPrev={() => setStepEnd(false)}
                    onPreview={handlePreviewClick}
                    onChange={() => setChange(true)}
                    />
                )}
            </div>
        </div>
         {/* 段落 */}
         {/* 1.3.0版本点击预览分段结果触发这个 */}
         {showSecondDiv && <div className="w-1/2 h-full relative">
            <FileUploadParagraphs open={showView} ref={viewRef} change={change} onChange={(change) => {
                setChange(change)
                document.getElementById('preview-btn')?.click()
            }} />
            {/* {!showView && (
                <div className="flex justify-center items-center flex-col h-full text-gray-400">
                    <FileText width={160} height={160} className="text-border" />
                    {stepEnd ? t('previewHint') : t('uploadHint')}
                </div>
            )} */}
        </div>} 
    </div>
};
