import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { useTranslation } from "react-i18next"

interface ViolationDialogProps {
    /** Null closes the dialog. */
    message: string | null
    onClose: () => void
}

/** Why a file cannot be previewed, shown in place of opening it. */
export function ViolationDialog({ message, onClose }: ViolationDialogProps) {
    const { t } = useTranslation()

    return (
        <Dialog open={Boolean(message)} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="gap-0 p-0 sm:max-w-[460px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>{t("build.tagConsole.violationTitle", "违规详情")}</DialogTitle>
                </DialogHeader>
                <div className="px-6 py-5">
                    <p className="rounded-md bg-[#FEF0F0] px-4 py-3 text-sm text-[#F53F3F] break-all">{message}</p>
                </div>
            </DialogContent>
        </Dialog>
    )
}
