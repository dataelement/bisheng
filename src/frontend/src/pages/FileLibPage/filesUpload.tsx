import { useTranslation } from "react-i18next";
import FileUploadStep1 from "./components/FileUploadStep1";
import FileUploadStep2 from "./components/FileUploadStep2";
import { useState } from "react";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { ReaderIcon } from "@radix-ui/react-icons";

export default function FilesUpload() {
    const { t } = useTranslation()
    const navigate = useNavigate();
    const [stepEnd, setStepEnd] = useState(false)

    return <div className="flex px-2 py-4 h-full gap-2">
        {/* 文件上传 */}
        <div className="w-[40%]">
            <div className="flex items-center">
                <ShadTooltip content="back" side="top">
                    <button className="extra-side-bar-buttons w-[36px]" onClick={() => navigate(-1)}  >
                        <ArrowLeft className="side-bar-button-size" />
                    </button>
                </ShadTooltip>
                <span className=" text-gray-700 text-sm font-black pl-4">返回</span>
            </div>
            {stepEnd ? <FileUploadStep2 onPrev={() => setStepEnd(false)} />
                : <FileUploadStep1 onNext={() => setStepEnd(true)} />}
        </div>
        {/* 段落 */}
        <div className="flex-1 bg-muted h-full">
            <div className="flex justify-center items-center flex-col h-full text-gray-400">
                <ReaderIcon width={160} height={160} className="text-border" />
                {stepEnd ? '左侧点击按钮预览结果' : '请先完成文件上传'}
            </div>
        </div>
    </div>
};
