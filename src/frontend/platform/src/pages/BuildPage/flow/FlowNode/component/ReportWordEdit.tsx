// @ts-strict-ignore
import { LoadingIcon } from "@/components/bs-icons/loading"
import { Button } from "@/components/bs-ui/button"
import { DialogClose } from "@/components/bs-ui/dialog"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { getWorkflowReportTemplate, saveWorkflowReportTemplate } from "@/controllers/API/workflow"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { uploadFileWithProgress } from "@/modals/UploadModal/upload"
import Word from "@/pages/Report/components/Word"
import { getOfficeReachableUrl } from "@/utils/officeUrl"
import { ChevronDown, ChevronLeft } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { useParams } from "react-router-dom"
import SelectVar from "./SelectVar"
// save(fe) -> office(onlyofc) -> upload(be)
export default function ReportWordEdit({ versionKey, nodeId, onChange }) {
    const { t } = useTranslation()
    const { message } = useToast()
    const { id: flowId } = useParams();
    const [saving, setSaving] = useState(false)

    const { docx, loading, pageLoading, createDocx, importDocx } = useReport(versionKey, flowId, onChange)

    // inset var
    const iframeRef = useRef(null)
    const handleInset = (value) => {
        if (!iframeRef.current) return
        const iframeDom = iframeRef.current.querySelector('iframe')
        if (!iframeDom) return
        // console.log('value :>> ', value);
        iframeDom.contentWindow.postMessage(JSON.stringify({
            type: "onExternalPluginMessage",
            action: 'insetMarker',
            data: value
        }), '*');
    }
    const [show, setShow] = useState(true) // 处理var select聚焦问题

    // Placeholders carry the node name so a template with several variables is
    // readable, but the backend still resolves values by node id — renaming a
    // node must not break an existing template. Strip the characters that would
    // break the `{{name|nodeId.field}}` shape out of the name.
    const buildMarker = (node, varValue: string) => {
        const key = `${node.id}.${varValue}`
        const displayName = (node.name || '').replace(/[{}|]/g, '').trim()
        return displayName ? `${displayName}|${key}` : key
    }

    // Manual save: auto-save fails silently often enough to lose edits, so the
    // user needs a way to force a flush. The document server writes the file
    // through its callback — a success here only means the command was accepted.
    const handleSave = async () => {
        if (saving) return
        setSaving(true)
        const res = await captureAndAlertRequestErrorHoc(saveWorkflowReportTemplate(docx.key, flowId))
        setSaving(false)
        // Failures are already surfaced by the request interceptor.
        if (res?.saved) {
            message({ description: t('report.saveSuccess'), variant: 'success' })
        }
    }

    if (pageLoading) return <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-primary/20">
        <LoadingIcon />
    </div>

    // new
    if (!docx.path) return <div className="relative size-full">
        <div className="absolute -top-10 z-10 flex gap-4">
            <DialogClose className="">
                <Button variant="outline" size="icon" className="bg-[#fff] size-8"><ChevronLeft /></Button>
            </DialogClose>
        </div>
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
                <div className="absolute -top-10 z-10 flex gap-4">
                    <DialogClose className="">
                        <Button variant="outline" size="icon" className="bg-[#fff] size-8"><ChevronLeft /></Button>
                    </DialogClose>
                    {show && <SelectVar
                        nodeId={nodeId}
                        itemKey={''}
                        align="normal"
                        onSelect={(E, v) => {
                            handleInset(buildMarker(E, v.value))
                            setShow(false)
                            setTimeout(() => {
                                setShow(true)
                            }, 1);
                        }}>
                        <Button className="h-8">{t('inserVar')}<ChevronDown size={14} /></Button>
                    </SelectVar>}
                    <Button className="h-8" disabled={saving} onClick={handleSave}>
                        {saving && <LoadingIcon className="mr-1 size-4" />}
                        {t('report.saveTemplate')}
                    </Button>
                </div>
                <Word data={docx} workflow></Word>
                {/* <LabelPanne onInset={handleInset}></LabelPanne> */}
            </div>
        </div>
    </div >
};


const useReport = (versionKey, flowId, onchange) => {
    const [loading, setLoading] = useState(false)
    const [pageLoading, setPageLoading] = useState(true)

    const [docx, setDocx] = useState({
        key: '',
        path: ''
    })

    useEffect(() => {
        getWorkflowReportTemplate(versionKey, flowId).then(res => {
            setPageLoading(false)
            setDocx({
                key: res.version_key,
                path: res.url
            })
            console.warn('REPORT:读取报告所用KEY是 :>> ', versionKey);
            console.warn('REPORT:读取报告所后变更KEY是 :>> ', res.version_key);
            onchange(res.version_key)
        })
    }, [])


    const handleCreate = async () => {
        // Must be an address the document server itself can fetch — in local dev
        // override it via VITE_OFFICE_PUBLIC_ORIGIN (see utils/officeUrl).
        setDocx(doc => ({ ...docx, path: getOfficeReachableUrl('/empty.docx') }))
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
        pageLoading,
        docx,
        createDocx: handleCreate,
        importDocx: handleImport
    }
}