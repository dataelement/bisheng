import { ChevronLeft } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "../../components/bs-ui/button";
import { getReportFormApi } from "../../controllers/API/flow";
import { uploadFileWithProgress } from "../../modals/UploadModal/upload";
import LabelPanne from "./components/Label";
import Word from "./components/Word";
import { LoadingIcon } from "@/components/bs-icons/loading";

export default function Report() {
    const { t } = useTranslation()

    const navigate = useNavigate()
    const { docx, loading, createDocx, importDocx } = useReport()

    // inset var
    const iframeRef = useRef(null)
    const handleInset = (value) => {
        if (!iframeRef.current) return
        const iframeDom = iframeRef.current.querySelector('iframe')
        if (!iframeDom) return
        iframeDom.contentWindow.postMessage(JSON.stringify({
            type: "onExternalPluginMessage",
            action: 'insetMarker',
            data: value
        }), '*');
    }

    return <div className="">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10">
            <LoadingIcon />
        </div>}
        <div className="absolute top-0 w-full flex justify-center items-center h-10 ">
            <span className="absolute left-10 flex items-center gap-1 cursor-pointer" onClick={() => navigate(-1)}><ChevronLeft size={20} />{t('back')}</span>
            <span className="text-sm">docx</span>
        </div>
        <div className="gap-4 flex h-screen p-10">
            <div ref={iframeRef} className="flex-1 border flex justify-center items-center bg-accent">
                {
                    docx.path
                        // office
                        ? <Word data={docx}></Word>
                        // create
                        : <div className="border rounded-md p-8 py-10 w-full max-w-[650px] bg-card">
                            <p className="text-xl">{t('report.reportTemplate')}</p>
                            <p className="text-sm mt-2">{t('report.reportDescription')}</p>
                            <div className="flex gap-2 mt-4">
                                <Button size="sm" className="w-full" onClick={createDocx}>{t('report.newButton')}</Button>
                                <Button variant="secondary" disabled={loading} size="sm" className="w-full border-gray-200" onClick={importDocx}>
                                    {loading && <span className="loading loading-spinner loading-sm pointer-events-none h-8 pl-3"></span>}
                                    {t('report.importButton')}
                                </Button>
                            </div>
                        </div>
                }
            </div>
            <div className="w-[240px] border px-4 pt-4 overflow-y-auto bg-accent">
                <LabelPanne onInset={handleInset}></LabelPanne>
            </div>
        </div>
    </div >
};


const useReport = () => {
    const [loading, setLoading] = useState(false)

    const [docx, setDocx] = useState({
        key: '',
        path: ''
    })
    // 获取编辑的文档
    const { id } = useParams()
    useEffect(() => {
        setLoading(true);
        /** 新建or编辑 key 由后端生成 */
        getReportFormApi(id).then(({ version_key, temp_url }) => {
            setLoading(false);
            setDocx({
                key: version_key,
                path: temp_url
            })
        })
    }, [id])


    const handleCreate = () => {
        setDocx({
            ...docx,
            // path: 'http://192.168.106.120:3002/empty.docx'
            path: location.origin + __APP_ENV__.BASE_URL + '/empty.docx' // 文档服务能访问到的文件地址
        })
    }

    const handleImport = () => {
        // 上传
        // Create a file input element
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".doc, .docx";
        input.style.display = "none"; // Hidden from view
        input.multiple = false; // Allow only one file selection

        input.onchange = (e: Event) => {
            setLoading(true);

            // Get the selected file
            const file = (e.target as HTMLInputElement).files?.[0];
            uploadFileWithProgress(file, (progress) => { }).then(res => {
                setLoading(false);
                setDocx({
                    ...docx,
                    path: res.file_path
                })
            })
        };

        input.click();
    }

    return {
        loading,
        docx,
        createDocx: handleCreate,
        importDocx: handleImport
    }
}