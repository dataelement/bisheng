import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input, Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import {
    createKnowledgeSpaceTagLibraryApi,
    updateKnowledgeSpaceTagLibraryApi,
    type KnowledgeSpaceTagLibraryDetail,
} from "@/controllers/API/knowledgeSpaceTagLibrary"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

const NAME_MAX_LENGTH = 20

interface TagLibraryFormDialogProps {
    open: boolean
    mode: "create" | "edit"
    initial?: KnowledgeSpaceTagLibraryDetail | null
    onOpenChange: (open: boolean) => void
    onSaved: () => void
}

export function TagLibraryFormDialog({ open, mode, initial, onOpenChange, onSaved }: TagLibraryFormDialogProps) {
    const { t } = useTranslation()
    const { toast } = useToast()
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        if (!open) return
        setName(initial?.name || "")
        setDescription(initial?.description || "")
    }, [open, initial])

    const handleSave = async () => {
        const trimmed = name.trim()
        if (!trimmed) {
            toast({ variant: "error", description: t("build.tagLibraryNameRequired", "标签库名称不能为空") })
            return
        }
        if (trimmed.length > NAME_MAX_LENGTH) {
            toast({ variant: "error", description: t("build.tagLibraryNameMaxLength", "标签库名称不能超过20个字符") })
            return
        }
        setSaving(true)
        const payload = { name: trimmed, description: description.trim() }
        const res = await captureAndAlertRequestErrorHoc(
            mode === "edit" && initial
                ? updateKnowledgeSpaceTagLibraryApi(initial.id, payload)
                : createKnowledgeSpaceTagLibraryApi({ ...payload, tags: [] }),
        )
        setSaving(false)
        if (!res) return
        toast({ variant: "success", description: t("build.saved", "已保存") })
        onOpenChange(false)
        onSaved()
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="gap-0 p-0 sm:max-w-[520px] bg-background-login">
                <DialogHeader className="border-b border-[#EBECF0] px-6 py-4">
                    <DialogTitle>
                        {mode === "edit"
                            ? t("build.editTagLibrary", "编辑标签库")
                            : t("build.createTagLibrary", "新增标签库")}
                    </DialogTitle>
                </DialogHeader>
                <div className="space-y-5 px-6 py-5">
                    <div>
                        <Label className="bisheng-label">
                            {t("build.tagLibraryName", "标签库名称")}
                            <span className="bisheng-tip">*</span>
                        </Label>
                        <Input
                            className="mt-2"
                            value={name}
                            maxLength={NAME_MAX_LENGTH}
                            autoComplete="off"
                            placeholder={t("build.tagLibraryNamePlaceholder", "请输入标签库名称")}
                            onChange={(e) => setName(e.target.value)}
                        />
                    </div>
                    <div>
                        <Label className="bisheng-label">{t("build.description", "说明")}</Label>
                        <Textarea
                            className="mt-2 min-h-20"
                            value={description}
                            maxLength={1000}
                            onChange={(e) => setDescription(e.target.value)}
                        />
                    </div>
                </div>
                <DialogFooter className="border-t border-[#EBECF0] px-6 py-3">
                    <Button variant="outline" className="px-8" onClick={() => onOpenChange(false)}>
                        {t("cancel", { ns: "bs" })}
                    </Button>
                    <Button className="px-8" disabled={saving} onClick={() => void handleSave()}>
                        {t("confirm", { ns: "bs" })}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
