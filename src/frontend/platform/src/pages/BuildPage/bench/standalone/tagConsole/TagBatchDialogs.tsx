import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select"
import type {
    KnowledgeSpaceTagLibraryListItem,
    TagConsoleBatchResult,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

interface LibraryPickerDialogProps {
    open: boolean
    title: string
    libraries: KnowledgeSpaceTagLibraryListItem[]
    saving: boolean
    onOpenChange: (open: boolean) => void
    onConfirm: (libraryId: number) => void
}

/** Shared by "move to library" and "approve into library". */
export function LibraryPickerDialog({
    open,
    title,
    libraries,
    saving,
    onOpenChange,
    onConfirm,
}: LibraryPickerDialogProps) {
    const { t } = useTranslation()
    const [libraryId, setLibraryId] = useState("")

    useEffect(() => {
        if (open) setLibraryId("")
    }, [open])

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[460px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <div className="px-6 py-5">
                    <Label className="bisheng-label">
                        {t("build.reviewTagSelectLibrary", "选择标签库")}
                        <span className="bisheng-tip">*</span>
                    </Label>
                    <Select value={libraryId} onValueChange={setLibraryId}>
                        <SelectTrigger className="mt-2">
                            <SelectValue placeholder={t("build.reviewTagSelectLibraryPlaceholder", "请选择标签库")} />
                        </SelectTrigger>
                        <SelectContent>
                            {libraries.map((library) => (
                                <SelectItem key={library.id} value={String(library.id)}>
                                    {library.name}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button
                        className="px-8"
                        disabled={saving || !libraryId}
                        onClick={() => onConfirm(Number(libraryId))}
                    >
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

interface RejectReasonDialogProps {
    open: boolean
    saving: boolean
    onOpenChange: (open: boolean) => void
    onConfirm: (reason: string) => void
}

export function RejectReasonDialog({ open, saving, onOpenChange, onConfirm }: RejectReasonDialogProps) {
    const { t } = useTranslation()
    const [reason, setReason] = useState("")

    useEffect(() => {
        if (open) setReason("")
    }, [open])

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[460px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.tagConsole.rejectTitle", "驳回标签")}</DialogTitle>
                </DialogHeader>
                <div className="px-6 py-5">
                    <Label className="bisheng-label">
                        {t("build.tagConsole.rejectReason", "驳回原因")}
                        <span className="bisheng-tip">*</span>
                    </Label>
                    <Textarea
                        className="mt-2 min-h-24"
                        value={reason}
                        maxLength={256}
                        placeholder={t("build.tagConsole.rejectReasonPlaceholder", "请填写驳回原因")}
                        onChange={(e) => setReason(e.target.value)}
                    />
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button className="px-8" disabled={saving || !reason.trim()} onClick={() => onConfirm(reason.trim())}>
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/**
 * Outcome of a batch run.
 *
 * Batches never roll back as a whole, so a partial failure has to show what
 * succeeded alongside what did not — reporting only the error would suggest
 * nothing happened.
 */
export function BatchResultDialog({
    result,
    onOpenChange,
}: {
    result: TagConsoleBatchResult | null
    onOpenChange: (open: boolean) => void
}) {
    const { t } = useTranslation()

    return (
        <Dialog open={Boolean(result)} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[520px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.tagConsole.batchResult", "处理结果")}</DialogTitle>
                </DialogHeader>
                <div className="space-y-3 px-6 py-5">
                    <p className="text-sm">
                        {t("build.tagConsole.batchSummary", "成功 {{ok}} 条，跳过 {{skipped}} 条，失败 {{failed}} 条", {
                            ok: result?.succeeded ?? 0,
                            skipped: result?.skipped ?? 0,
                            failed: result?.failed?.length ?? 0,
                        })}
                    </p>
                    {Boolean(result?.failed?.length) && (
                        <div className="max-h-60 overflow-y-auto rounded-md border border-[#ECECEC] bg-[#FAFBFC] p-3">
                            {result?.failed.map((item, index) => (
                                <div key={`${item.name}-${index}`} className="py-1 text-sm">
                                    <span className="font-medium">{item.name}</span>
                                    <span className="ml-2 text-muted-foreground">{item.reason}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button className="px-8" onClick={() => onOpenChange(false)}>
                        {t("close", { ns: "bs", defaultValue: "关闭" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
