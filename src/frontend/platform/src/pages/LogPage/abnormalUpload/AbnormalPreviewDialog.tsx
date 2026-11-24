import { Dialog, DialogContent, DialogTitle } from "@/components/bs-ui/dialog"
import { getAbnormalFilePreview, type AbnormalUploadItem } from "@/controllers/API/abnormalUpload"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { selectPreviewSource, type PreviewSource } from "./previewSource"
import PreviewBody from "./AbnormalPreviewBody"

interface Props {
    row: AbnormalUploadItem
    trigger: HTMLButtonElement
    onClose: () => void
}

export function loadAbnormalPreview(row: Pick<AbnormalUploadItem, 'knowledge_id' | 'file_id' | 'file_name'>, signal: AbortSignal, onReady: (source: PreviewSource) => void, onError: (key: string) => void) {
    return getAbnormalFilePreview(row.knowledge_id, row.file_id, signal).then(detail => {
        if (signal.aborted) return
        const next = selectPreviewSource(detail, row.file_name)
        if (next) onReady(next)
        else onError('com_sop_preview_failed')
    }).catch(error => {
        if (signal.aborted) return
        const code = error?.response?.data?.status_code ?? error?.status_code
        onError(Number.isInteger(code) ? `errors.${code}` : 'com_sop_preview_failed')
    })
}

export default function AbnormalPreviewDialog({ row, trigger, onClose }: Props) {
    const { t } = useTranslation()
    const [source, setSource] = useState<PreviewSource | null>(null)
    const [errorKey, setErrorKey] = useState("")
    const handleError = useCallback(() => setErrorKey("com_sop_preview_failed"), [])
    useEffect(() => {
        const request = new AbortController()
        void loadAbnormalPreview(row, request.signal, setSource, setErrorKey)
        return () => request.abort()
    }, [row, handleError])

    const loading = <p role="status">{t("log.abnormalLoading")}</p>
    return <Dialog open onOpenChange={open => { if (!open) onClose() }}>
        <DialogContent aria-describedby={undefined} className="flex h-[80vh] w-[90vw] max-w-5xl flex-col" onCloseAutoFocus={event => {
            event.preventDefault()
            trigger.focus()
        }}>
            <DialogTitle className="break-all pr-8">{row.file_name}</DialogTitle>
            <div className="relative min-h-0 flex-1 overflow-auto">
                {errorKey ? <p role="alert">{t(errorKey, { defaultValue: t("com_sop_preview_failed") })}</p>
                    : source ? <PreviewBody source={source} onError={handleError} /> : loading}
            </div>
        </DialogContent>
    </Dialog>
}
