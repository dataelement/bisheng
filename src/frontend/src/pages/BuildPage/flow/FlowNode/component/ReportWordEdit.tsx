import { LoadingIcon } from "@/components/bs-icons/loading"
import { Button } from "@/components/bs-ui/button"
import { uploadFileWithProgress } from "@/modals/UploadModal/upload"
import Word from "@/pages/Report/components/Word"
import { ChevronDown } from "lucide-react"
import { useTranslation } from "react-i18next"
import SelectVar from "./SelectVar"
// save(fe) -> office(onlyofc) -> upload(be)
export default function ReportWordEdit({ versionKey, nodeId, onChange }) {
    const { t } = useTranslation()

    const { docx, loading, createDocx, importDocx } = useReport(versionKey, onChange)

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

    // new
    if (!docx.path) return <div className="flex size-full">
        <div className="bg-accent size-full flex justify-center items-center">
            <div className="border rounded-md p-8 py-10 w-1/2 bg-card">
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
        </div>
    </div>

    return <div className="relative size-full">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-primary/20">
            <LoadingIcon />
        </div>}
        <div className="flex h-full">
            <div ref={iframeRef} className="relative flex-1 border bg-accent">
                <div className="absolute right-10 top-2 z-10">
                    <SelectVar nodeId={nodeId} itemKey={''} onSelect={(E, v) => handleInset(`${E.id}.${v.value}`)}>
                        <Button variant="black" className="h-8">插入变量 <ChevronDown size={14} /></Button>
                    </SelectVar>
                </div>
                <Word data={docx} workflow></Word>
                {/* <LabelPanne onInset={handleInset}></LabelPanne> */}
            </div>
        </div>
    </div >
};


const useReport = (versionKey, onchange) => {
    const [loading, setLoading] = useState(false)

    const [docx, setDocx] = useState({
        key: '',
        path: ''
    })

    useEffect(() => {
        getWorkflowReportTemplate(versionKey).then(res => {
            setDocx({
                key: res.version_key,
                path: res.url
            })
            onchange(res.version_key)
        })
    }, [])


    const handleCreate = async () => {
        setDocx(docx => ({ ...docx, path: 'http://192.168.106.120:3002/empty.docx' }))
        // setDocx(doc => ({...docx, path: location.origin + __APP_ENV__.BASE_URL + '/empty.docx'})// 文档服务能访问到的文件地址
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
                setDocx(docx => ({ ...docx, path: res.file_path }))
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