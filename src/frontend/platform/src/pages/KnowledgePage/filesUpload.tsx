import ShadTooltip from "@/components/ShadTooltipComponent";
import { ArrowLeft, FileText } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import FileUploadParagraphs from "./components/FileUploadParagraphs";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";

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
    const handleStep1NextClick = (fileInfo) => {
        setFileInfo(fileInfo)
        setStepEnd(true)
        setShowView(false)
    }

    return <div className="flex px-2 py-4 h-full gap-2">
        {/* 文件上传 */}
        <div className="w-[44%] min-w-[520px]">
            <div className="flex items-center">
                <ShadTooltip content="back" side="top">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => navigate(-1)}  >
                        <ArrowLeft className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                <span className=" text-foreground text-sm font-black pl-4">{t('back')}</span>
            </div>
            <FileUploadStep1 hidden={stepEnd} onNext={handleStep1NextClick} onChange={() => setChange(true)} />
            {stepEnd && (
                <FileUploadStep2
                    fileInfo={fileInfo}
                    onPrev={() => setStepEnd(false)}
                    onPreview={handlePreviewClick}
                    onChange={() => setChange(true)}
                />
            )}
        </div>
        {/* 段落 */}
        <div className="flex-1 bg-muted h-full relative overflow-x-auto">
            <FileUploadParagraphs open={showView} ref={viewRef} change={change} onChange={(change) => {
                setChange(change)
                document.getElementById('preview-btn')?.click()
            }} />
            {!showView && (
                <div className="flex justify-center items-center flex-col h-full text-gray-400">
                    <FileText width={160} height={160} className="text-border" />
                    {stepEnd ? t('previewHint') : t('uploadHint')}
                </div>
            )}
        </div>
    </div>
};
